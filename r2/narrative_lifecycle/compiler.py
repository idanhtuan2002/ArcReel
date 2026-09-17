"""The pure M5C ``CanonDeltaCompiler``: accepted Narrative evidence -> one M5A ``CanonDelta``.

The compiler holds no async dependency, clock, random source, provider, database,
repository, unit of work, writer, acceptance service, or Canon transaction service. Every
input is an exact immutable snapshot loaded before invocation; ``CompilationOutputIdentity``
supplies the attempt-bound ``canon_delta_id`` / ``created_at`` / ``created_by`` so no opaque
id is generated and no wall clock is read here. Compilation is total: every contract,
policy, or business condition comes back as an ordered ``CanonDeltaCompilation`` outcome
(``SUCCEEDED`` / ``NO_CANON_MUTATION`` / ``ABSTAINED`` / ``CONFLICT`` / ``FAILED``), never as
a raised ``CanonDeltaCompilationError`` and never as a partial delta.

Determinism: the same input values and version selectors produce the same terminal outcome,
the same ordered findings, the same ordered operations and derived operation ids, the same
source / author decision refs, and the same payload hash. Nothing iterates an unordered
set; every traversal is over an explicitly sorted sequence, so the process hash seed,
locale, and database row order cannot influence the result.

Two opaque free-text fields become exact here for the first time. Both are versioned:

``effect_descriptor`` (on ``CanonMutationEffectKey``) — ``EFFECT_RULE_KEY_VERSION``
    The descriptor carries no grammar of its own: no prefix, namespace, separator, or
    structure is parsed out of it. It acquires meaning only by matching a
    ``CanonMutationRule`` in the active ``CompilerPolicy`` on the exact triple
    ``(canon_subject_kind, subject_ref, effect_descriptor)``. A rule supplies the complete
    M5A operation content the effect expands to; the compiler never templates, guesses, or
    partially fills an operation. An effect key with no matching rule is unsupported, a rule
    whose operation count differs from the key's ``canon_operation_count`` is underspecified,
    and a rule emitting an operation kind outside ``operation_kinds_for(<canon schema>)`` is
    unsupported for that base — all three ``ABSTAIN`` rather than convert by best effort.
    Two rules on one triple make the policy ambiguous and ``FAIL``.

``chosen_resolution`` (on ``ConflictResolutionCommand``) — ``RESOLUTION_INSTRUCTION_VERSION``
    An exact three-part instruction, colon separated, no optional whitespace::

        r2-m5c-conflict-resolution-instruction-v1:KEEP:<change_set_id>
        r2-m5c-conflict-resolution-instruction-v1:COMBINE:<change_set_id>,<change_set_id>[,...]
        r2-m5c-conflict-resolution-instruction-v1:REPLACE:<replacement_ref>

    ``KEEP`` selects one competitor and drops the others' effects. ``COMBINE`` retains every
    competitor named — the argument must list exactly the decision's competing change sets —
    and is legal only while their typed effect keys do not collide under the policy's
    collision policy; a still-colliding combine stays a ``CONFLICT``. ``REPLACE`` drops every
    competitor and substitutes the typed effect keys of the policy's ``ReplacementEffectRule``
    with that ``replacement_ref``; an unknown ref ``ABSTAINS`` (the policy does not support
    it). A substituted effect then faces the same collision rule every change set faces —
    against each retained change set and against every other substitution — so a replacement
    that reintroduces a collision stays a ``CONFLICT``. Any other version prefix, kind, shape,
    or argument fails closed.

Operation ids are content-addressed under ``OPERATION_ID_DERIVATION_VERSION`` from the
effect key, the rule ordinal, and the operation body — the one derived-id rule §9.5 allows.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import TypeAdapter, ValidationError

from r2.contracts import canonical_json_bytes, ensure_json_value
from r2.contracts.narrative import (
    CANON_SCHEMA_V1,
    CANON_SCHEMA_V2,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    operation_kinds_for,
)
from r2.contracts.narrative_lifecycle import (
    SEMANTIC_EFFECT_KEY_VERSION,
    CanonMutationEffectKey,
    CompilationAttempt,
    ConflictResolutionCommand,
    NarrativeChangeSet,
    NarrativeRevision,
    NarrativeSemanticEffectKey,
)
from r2.narrative.hashing import compute_canon_delta_hash
from r2.narrative_lifecycle.coverage import (
    EffectKeyCollisionPolicy,
    coverage_contains,
    effect_keys_collide,
    normalize_effect_keys,
    normalize_source_spans,
    spans_overlap,
)

COMPILER_VERSION = "r2-m5c-canon-delta-compiler-v1"
COMPILER_POLICY_VERSION = "r2-m5c-canon-delta-compiler-policy-v1"
EFFECT_RULE_KEY_VERSION = "r2-m5c-compiler-effect-rule-key-v1"
RESOLUTION_INSTRUCTION_VERSION = "r2-m5c-conflict-resolution-instruction-v1"
OPERATION_ID_DERIVATION_VERSION = "r2-m5c-canon-operation-id-v1"

SUPPORTED_COMPILER_VERSIONS: frozenset[str] = frozenset({COMPILER_VERSION})
SUPPORTED_COMPILER_POLICY_VERSIONS: frozenset[str] = frozenset({COMPILER_POLICY_VERSION})
SUPPORTED_SEMANTIC_EFFECT_KEY_VERSIONS: frozenset[str] = frozenset({SEMANTIC_EFFECT_KEY_VERSION})
SUPPORTED_CANON_SCHEMA_VERSIONS: frozenset[str] = frozenset({CANON_SCHEMA_V1, CANON_SCHEMA_V2})

ResolutionInstructionKind = Literal["KEEP", "COMBINE", "REPLACE"]
_RESOLUTION_INSTRUCTION_KINDS: frozenset[str] = frozenset({"KEEP", "COMBINE", "REPLACE"})

_CANON_OPERATION_ADAPTER: TypeAdapter[CanonOperation] = TypeAdapter(CanonOperation)


# --- findings and outcomes ----------------------------------------------------


@dataclass(frozen=True)
class CompilerFinding:
    """One ordered, machine-readable reason. ``ref`` is the stable reference the resulting
    delta records in ``validation_report_refs`` when the compilation still succeeds."""

    code: str
    message: str
    refs: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"cf:{self.code}" if not self.refs else f"cf:{self.code}:{'+'.join(self.refs)}"


@dataclass(frozen=True)
class CompilationSucceeded:
    """A complete, non-empty M5A ``CanonDelta`` proposal. It grants no Canon authority."""

    canon_delta: CanonDelta
    findings: tuple[CompilerFinding, ...] = ()
    outcome: ClassVar[str] = "SUCCEEDED"


@dataclass(frozen=True)
class _NoDeltaCompilation:
    findings: tuple[CompilerFinding, ...] = ()
    canon_delta: ClassVar[None] = None
    outcome: ClassVar[str] = ""


@dataclass(frozen=True)
class CompilationNoCanonMutation(_NoDeltaCompilation):
    """The complete valid resolved selection is outcome-only: zero ``CanonMutationEffectKey``
    values survive resolution. A deterministic terminal result, not an abstention."""

    outcome: ClassVar[str] = "NO_CANON_MUTATION"


@dataclass(frozen=True)
class CompilationAbstained(_NoDeltaCompilation):
    """A selected Canon-mutation effect is unsupported or underspecified by the exact policy
    and Canon schema. Never relabelled ``NO_CANON_MUTATION``."""

    outcome: ClassVar[str] = "ABSTAINED"


@dataclass(frozen=True)
class CompilationConflict(_NoDeltaCompilation):
    """A detected overlap is unresolved, multiply resolved, or still colliding after an
    explicit combine."""

    outcome: ClassVar[str] = "CONFLICT"


@dataclass(frozen=True)
class CompilationFailed(_NoDeltaCompilation):
    """An input is unsupported, inconsistent with its admitted attempt, or malformed."""

    outcome: ClassVar[str] = "FAILED"


_NonDeltaCompilation = CompilationNoCanonMutation | CompilationAbstained | CompilationConflict | CompilationFailed

CanonDeltaCompilation = (
    CompilationSucceeded | CompilationNoCanonMutation | CompilationAbstained | CompilationConflict | CompilationFailed
)


# --- exact compiler inputs ----------------------------------------------------


@dataclass(frozen=True)
class ReviewedChangeSet:
    """One accepted change set paired with the exact review decision that selected it. The
    pair is never re-derived from the change set alone."""

    change_set: NarrativeChangeSet
    review_decision_id: str


@dataclass(frozen=True)
class ExactCanonBase:
    """The exact Canon base the delta is proposed against. ``content_schema_version`` selects
    which M5A operation kinds are legal; it is never inferred from the operations emitted."""

    canon_branch_id: str
    base_canon_version_id: str
    content_schema_version: str = CANON_SCHEMA_V1


@dataclass(frozen=True)
class CompilationOutputIdentity:
    """The attempt-bound output identity. It carries the admitted ``CompilationAttempt`` —
    the immutable snapshot the compiler validates its inputs against — plus the
    ``canon_delta_id``, ``created_at``, and ``created_by`` the attempt already fixed, so the
    compiler generates no id and reads no clock. ``from_attempt`` is a convenience, not the
    gate: validation step 2 compares all three against ``requested_canon_delta_id`` /
    ``delta_created_at`` / ``delta_created_by``, so a directly constructed identity that
    contradicts its own attempt is ``FAILED``. ``expected_payload_hash``, when supplied, must
    equal the recomputed M5A hash or the compilation fails."""

    attempt: CompilationAttempt
    canon_delta_id: str
    created_at: datetime
    created_by: str
    expected_payload_hash: str | None = None

    @classmethod
    def from_attempt(
        cls, attempt: CompilationAttempt, *, expected_payload_hash: str | None = None
    ) -> CompilationOutputIdentity:
        return cls(
            attempt=attempt,
            canon_delta_id=attempt.requested_canon_delta_id,
            created_at=attempt.delta_created_at,
            created_by=attempt.delta_created_by,
            expected_payload_hash=expected_payload_hash,
        )


@dataclass(frozen=True)
class CanonMutationRule:
    """The complete M5A operation content one exact effect-key triple expands to, under
    ``EFFECT_RULE_KEY_VERSION``. ``operations`` carry placeholder ``operation_id`` values that
    the compiler restamps with content-addressed ids."""

    canon_subject_kind: str
    subject_ref: str
    effect_descriptor: str
    operations: tuple[CanonOperation, ...]


@dataclass(frozen=True)
class ReplacementEffectRule:
    """The typed effect keys a ``REPLACE`` resolution instruction may substitute for the
    competitors it drops."""

    replacement_ref: str
    effect_keys: tuple[NarrativeSemanticEffectKey, ...]


@dataclass(frozen=True)
class CompilerPolicy:
    """The exact, versioned rule set the compilation runs under. It holds no callable,
    provider, or clock: equality and determinism are structural."""

    policy_ref: str
    policy_version: str = COMPILER_POLICY_VERSION
    collision_policy: EffectKeyCollisionPolicy = "SAME_SUBJECT"
    mutation_rules: tuple[CanonMutationRule, ...] = ()
    replacement_rules: tuple[ReplacementEffectRule, ...] = field(default=())


@dataclass(frozen=True)
class _ResolutionInstruction:
    kind: ResolutionInstructionKind
    argument: str

    @property
    def change_set_ids(self) -> tuple[str, ...]:
        return tuple(part for part in self.argument.split(","))


# --- pure helpers -------------------------------------------------------------


def _finding(code: str, message: str, *refs: str) -> CompilerFinding:
    return CompilerFinding(code=code, message=message, refs=tuple(refs))


def _failed(code: str, message: str, *refs: str) -> CompilationFailed:
    return CompilationFailed(findings=(_finding(code, message, *refs),))


def _abstained(code: str, message: str, *refs: str) -> CompilationAbstained:
    return CompilationAbstained(findings=(_finding(code, message, *refs),))


def _conflict(code: str, message: str, *refs: str) -> CompilationConflict:
    return CompilationConflict(findings=(_finding(code, message, *refs),))


def _rule_key(canon_subject_kind: str, subject_ref: str, effect_descriptor: str) -> tuple[str, str, str]:
    return (canon_subject_kind, subject_ref, effect_descriptor)


def _derive_operation_id(effect_key: CanonMutationEffectKey, ordinal: int, body: dict[str, object]) -> str:
    """The one derived subordinate id §9.5 permits: content-addressed, versioned, and free of
    wall clock, counter, and process state."""
    preimage = {
        "rule_version": OPERATION_ID_DERIVATION_VERSION,
        "effect_key": effect_key.model_dump(mode="json"),
        "ordinal": ordinal,
        "operation": body,
    }
    digest = hashlib.sha256(canonical_json_bytes(ensure_json_value(preimage))).hexdigest()
    return f"op-{digest[:32]}"


def _parse_resolution_instruction(text: str) -> _ResolutionInstruction | str:
    """Parse one ``chosen_resolution``. Returns the instruction, or a finding code naming why
    the exact ``RESOLUTION_INSTRUCTION_VERSION`` grammar rejected it."""
    parts = text.split(":", 2)
    if len(parts) != 3 or parts[0] != RESOLUTION_INSTRUCTION_VERSION or not parts[2]:
        return "MALFORMED_RESOLUTION_INSTRUCTION"
    kind = parts[1]
    if kind not in _RESOLUTION_INSTRUCTION_KINDS:
        return "UNKNOWN_RESOLUTION_KIND"
    argument = parts[2]
    if kind == "COMBINE":
        named = argument.split(",")
        if len(named) < 2 or any(not item for item in named) or len(set(named)) != len(named):
            return "MALFORMED_RESOLUTION_INSTRUCTION"
    elif "," in argument:
        return "MALFORMED_RESOLUTION_INSTRUCTION"
    return _ResolutionInstruction(kind=kind, argument=argument)  # pyright: ignore[reportArgumentType]


def _change_sets_conflict(
    left: NarrativeChangeSet, right: NarrativeChangeSet, *, collision_policy: EffectKeyCollisionPolicy
) -> bool:
    left_spans = normalize_source_spans(left.source_spans)
    right_spans = normalize_source_spans(right.source_spans)
    if any(spans_overlap(a, b) for a in left_spans for b in right_spans):
        return True
    return _effect_keys_collide_across(
        normalize_effect_keys(left.semantic_effect_keys),
        normalize_effect_keys(right.semantic_effect_keys),
        collision_policy=collision_policy,
    )


def _effect_keys_collide_across(
    left: Sequence[NarrativeSemanticEffectKey],
    right: Sequence[NarrativeSemanticEffectKey],
    *,
    collision_policy: EffectKeyCollisionPolicy,
) -> bool:
    return any(effect_keys_collide(a, b, policy=collision_policy) for a in left for b in right)


class CanonDeltaCompiler:
    """Compiles one admitted ``CompilationAttempt``'s exact immutable snapshot into at most
    one M5A ``CanonDelta``. It never asks whether a decision is still current — currentness
    belongs to attempt admission and to the separate handoff admission."""

    compiler_version: ClassVar[str] = COMPILER_VERSION

    def compile(
        self,
        output_identity: CompilationOutputIdentity,
        revision: NarrativeRevision,
        reviewed_change_sets: Sequence[ReviewedChangeSet],
        conflict_resolutions: Sequence[ConflictResolutionCommand],
        exact_canon_base: ExactCanonBase,
        compiler_policy: CompilerPolicy,
    ) -> CanonDeltaCompilation:
        attempt = output_identity.attempt
        ordered_change_sets = sorted(reviewed_change_sets, key=lambda item: item.change_set.change_set_id)
        ordered_resolutions = sorted(conflict_resolutions, key=lambda item: item.decision_id)

        versions = self._validate_versions(attempt, exact_canon_base, ordered_change_sets, compiler_policy)
        if versions is not None:
            return CompilationFailed(findings=(versions,))

        identity = self._validate_identity(output_identity, revision, exact_canon_base, ordered_change_sets)
        if identity is not None:
            return CompilationFailed(findings=(identity,))

        selection = self._validate_selection(attempt, ordered_change_sets, ordered_resolutions)
        if selection is not None:
            return CompilationFailed(findings=(selection,))

        coverage = self._validate_coverage(ordered_change_sets)
        if coverage is not None:
            return CompilationFailed(findings=(coverage,))

        resolved = self._resolve_conflicts(ordered_change_sets, ordered_resolutions, compiler_policy)
        if not isinstance(resolved, tuple):
            return resolved

        retained, replacement_keys = resolved
        effective_keys = normalize_effect_keys(
            [key for item in retained for key in item.change_set.semantic_effect_keys] + list(replacement_keys)
        )
        mutation_keys = [key for key in effective_keys if isinstance(key, CanonMutationEffectKey)]
        if not mutation_keys:
            return CompilationNoCanonMutation(
                findings=(
                    _finding(
                        "OUTCOME_ONLY_SELECTION",
                        "the complete valid resolved selection declares no Canon-mutation effect",
                        *(item.change_set.change_set_id for item in retained),
                    ),
                )
            )

        operations = self._map_operations(mutation_keys, exact_canon_base, compiler_policy)
        if not isinstance(operations, list):
            return operations

        return self._seal(output_identity, attempt, exact_canon_base, operations)

    # --- §9.2 step 1: supported versions --------------------------------------

    def _validate_versions(
        self,
        attempt: CompilationAttempt,
        exact_canon_base: ExactCanonBase,
        ordered_change_sets: Sequence[ReviewedChangeSet],
        compiler_policy: CompilerPolicy,
    ) -> CompilerFinding | None:
        if attempt.compiler_version not in SUPPORTED_COMPILER_VERSIONS:
            return _finding(
                "UNSUPPORTED_COMPILER_VERSION",
                f"attempt names compiler version {attempt.compiler_version!r}",
            )
        if compiler_policy.policy_version not in SUPPORTED_COMPILER_POLICY_VERSIONS:
            return _finding(
                "UNSUPPORTED_POLICY_VERSION",
                f"policy version {compiler_policy.policy_version!r} is outside this compiler's support set",
            )
        if (attempt.creative_policy_ref, attempt.creative_policy_version) != (
            compiler_policy.policy_ref,
            compiler_policy.policy_version,
        ):
            return _finding(
                "POLICY_BINDING_MISMATCH",
                "the supplied policy is not the exact creative policy the attempt was admitted under",
            )
        if exact_canon_base.content_schema_version not in SUPPORTED_CANON_SCHEMA_VERSIONS:
            return _finding(
                "UNSUPPORTED_CANON_SCHEMA_VERSION",
                f"Canon content schema {exact_canon_base.content_schema_version!r} is not supported",
            )
        for item in ordered_change_sets:
            for key in item.change_set.semantic_effect_keys:
                if key.mapping_version not in SUPPORTED_SEMANTIC_EFFECT_KEY_VERSIONS:
                    return _finding(
                        "UNSUPPORTED_EFFECT_KEY_VERSION",
                        f"effect-key mapping version {key.mapping_version!r} is not supported",
                        item.change_set.change_set_id,
                    )
        duplicates = self._ambiguous_rule_keys(compiler_policy)
        if duplicates:
            return _finding(
                "AMBIGUOUS_POLICY_RULE",
                "the policy declares more than one rule for one exact effect-key triple",
                *duplicates,
            )
        return None

    @staticmethod
    def _ambiguous_rule_keys(compiler_policy: CompilerPolicy) -> tuple[str, ...]:
        seen: dict[tuple[str, str, str], int] = {}
        for rule in compiler_policy.mutation_rules:
            key = _rule_key(rule.canon_subject_kind, rule.subject_ref, rule.effect_descriptor)
            seen[key] = seen.get(key, 0) + 1
        duplicated = sorted("/".join(key) for key, count in seen.items() if count > 1)
        replacements: dict[str, int] = {}
        for replacement in compiler_policy.replacement_rules:
            replacements[replacement.replacement_ref] = replacements.get(replacement.replacement_ref, 0) + 1
        duplicated += sorted(ref for ref, count in replacements.items() if count > 1)
        return tuple(duplicated)

    # --- §9.2 steps 2-3: scope, revision, Canon base identity -----------------

    def _validate_identity(
        self,
        output_identity: CompilationOutputIdentity,
        revision: NarrativeRevision,
        exact_canon_base: ExactCanonBase,
        ordered_change_sets: Sequence[ReviewedChangeSet],
    ) -> CompilerFinding | None:
        attempt = output_identity.attempt
        # Step 2 owns the output identity too: §9.5 fixes the opaque delta id and the output
        # timestamp in the admitted attempt, so a directly constructed identity that
        # contradicts its own attempt is rejected rather than silently preferred.
        supplied_identity = (output_identity.canon_delta_id, output_identity.created_at, output_identity.created_by)
        admitted_identity = (attempt.requested_canon_delta_id, attempt.delta_created_at, attempt.delta_created_by)
        if supplied_identity != admitted_identity:
            return _finding(
                "OUTPUT_IDENTITY_MISMATCH",
                "the output identity's delta id, created_at, or created_by is not the admitted attempt's",
                attempt.attempt_id,
            )
        if revision.work_scope != attempt.work_scope:
            return _finding("WORK_SCOPE_MISMATCH", "the revision's work scope is not the attempt's work scope")
        if revision.revision_id != attempt.revision_id:
            return _finding(
                "REVISION_IDENTITY_MISMATCH",
                f"attempt names revision {attempt.revision_id!r}, not {revision.revision_id!r}",
            )
        if attempt.work_scope.canon_branch_id != exact_canon_base.canon_branch_id:
            return _finding(
                "CANON_BRANCH_MISMATCH",
                f"the exact Canon base names branch {exact_canon_base.canon_branch_id!r}",
            )
        if attempt.base_canon_version_id != exact_canon_base.base_canon_version_id:
            return _finding(
                "CANON_BASE_MISMATCH",
                f"attempt is based on {attempt.base_canon_version_id!r}, "
                f"not {exact_canon_base.base_canon_version_id!r}",
            )
        if revision.base_canon_version_id != exact_canon_base.base_canon_version_id:
            return _finding("CANON_BASE_MISMATCH", "the revision is based on a different Canon version")
        for item in ordered_change_sets:
            if item.change_set.source_revision_id != revision.revision_id:
                return _finding(
                    "CHANGE_SET_SOURCE_REVISION_MISMATCH",
                    "a selected change set was extracted from another revision",
                    item.change_set.change_set_id,
                )
            if item.change_set.base_canon_version_id != exact_canon_base.base_canon_version_id:
                return _finding(
                    "CANON_BASE_MISMATCH",
                    "a selected change set is based on a different Canon version",
                    item.change_set.change_set_id,
                )
        return None

    # --- §9.2 steps 4-5: attempt-pair equality and lineage uniqueness ---------

    def _validate_selection(
        self,
        attempt: CompilationAttempt,
        ordered_change_sets: Sequence[ReviewedChangeSet],
        ordered_resolutions: Sequence[ConflictResolutionCommand],
    ) -> CompilerFinding | None:
        admitted = sorted(
            (selected.change_set_id, selected.review_decision_id) for selected in attempt.selected_change_sets
        )
        supplied = sorted((item.change_set.change_set_id, item.review_decision_id) for item in ordered_change_sets)
        if admitted != supplied:
            return _finding(
                "SELECTION_MISMATCH",
                "the supplied accepted change-set/review-decision pairs are not the attempt's exact selection",
            )
        if sorted(attempt.conflict_resolution_decision_ids) != sorted(item.decision_id for item in ordered_resolutions):
            return _finding(
                "RESOLUTION_SELECTION_MISMATCH",
                "the supplied conflict resolutions are not the attempt's exact resolution decisions",
            )
        for resolution in ordered_resolutions:
            if resolution.action != "RESOLVE":
                return _finding(
                    "NON_RESOLVING_RESOLUTION_ACTION",
                    f"resolution decision names action {resolution.action!r}",
                    resolution.decision_id,
                )
            if resolution.work_scope != attempt.work_scope:
                return _finding(
                    "WORK_SCOPE_MISMATCH", "a resolution decision belongs to another work scope", resolution.decision_id
                )
            if resolution.revision_acceptance_decision_id != attempt.revision_acceptance_decision_id:
                return _finding(
                    "RESOLUTION_SELECTION_MISMATCH",
                    "a resolution decision belongs to another accepted revision",
                    resolution.decision_id,
                )
        lineages: dict[str, str] = {}
        for item in ordered_change_sets:
            lineage = item.change_set.change_set_lineage_id
            if lineage in lineages:
                return _finding(
                    "DUPLICATE_CHANGE_SET_LINEAGE",
                    f"lineage {lineage!r} contributes two alternative proposals to one compilation",
                    lineages[lineage],
                    item.change_set.change_set_id,
                )
            lineages[lineage] = item.change_set.change_set_id
        return None

    # --- §9.2 step 6: coverage validity ---------------------------------------

    def _validate_coverage(self, ordered_change_sets: Sequence[ReviewedChangeSet]) -> CompilerFinding | None:
        for item in ordered_change_sets:
            change_set = item.change_set
            if not change_set.source_spans or not change_set.semantic_effect_keys:
                return _finding(
                    "COVERAGE_VIOLATION",
                    "a selected change set declares no source span or no semantic effect key",
                    change_set.change_set_id,
                )
            declared = set(change_set.semantic_effect_keys)
            for change in change_set.changes:
                if not coverage_contains(change.evidence_span, change_set.source_spans):
                    return _finding(
                        "COVERAGE_VIOLATION",
                        f"change {change.change_id!r} lies outside the declared source-span coverage",
                        change_set.change_set_id,
                    )
                if not declared.issuperset(change.effect_keys):
                    return _finding(
                        "UNDECLARED_EFFECT_KEY",
                        f"change {change.change_id!r} names an effect key the change set does not declare",
                        change_set.change_set_id,
                    )
        return None

    # --- §9.2 steps 7-8 / §9.3: overlap analysis and resolution coverage ------

    def _resolve_conflicts(
        self,
        ordered_change_sets: Sequence[ReviewedChangeSet],
        ordered_resolutions: Sequence[ConflictResolutionCommand],
        compiler_policy: CompilerPolicy,
    ) -> tuple[list[ReviewedChangeSet], tuple[NarrativeSemanticEffectKey, ...]] | _NonDeltaCompilation:
        by_id = {item.change_set.change_set_id: item for item in ordered_change_sets}
        review_decision_by_id = {item.change_set.change_set_id: item.review_decision_id for item in ordered_change_sets}

        instructions: dict[str, _ResolutionInstruction] = {}
        for resolution in ordered_resolutions:
            outside = [ref for ref in sorted(resolution.competing_change_set_ids) if ref not in by_id]
            if outside:
                return _failed(
                    "RESOLUTION_OUTSIDE_SELECTION",
                    "a resolution names a change set outside the admitted selection",
                    resolution.decision_id,
                    *outside,
                )
            paired = dict(
                zip(resolution.competing_change_set_ids, resolution.competing_review_decision_ids, strict=True)
            )
            for change_set_id in sorted(paired):
                if paired[change_set_id] != review_decision_by_id[change_set_id]:
                    return _failed(
                        "RESOLUTION_REVIEW_DECISION_MISMATCH",
                        "a resolution names a review decision the attempt did not select",
                        resolution.decision_id,
                        change_set_id,
                    )
            parsed = _parse_resolution_instruction(resolution.chosen_resolution)
            if isinstance(parsed, str):
                return _failed(
                    parsed,
                    f"chosen_resolution is not a {RESOLUTION_INSTRUCTION_VERSION} instruction",
                    resolution.decision_id,
                )
            named = set(resolution.competing_change_set_ids)
            if parsed.kind == "KEEP" and parsed.argument not in named:
                return _failed(
                    "MALFORMED_RESOLUTION_INSTRUCTION",
                    "a KEEP instruction names a change set outside its own competing set",
                    resolution.decision_id,
                )
            if parsed.kind == "COMBINE" and set(parsed.change_set_ids) != named:
                return _failed(
                    "MALFORMED_RESOLUTION_INSTRUCTION",
                    "a COMBINE instruction must name exactly its own competing change sets",
                    resolution.decision_id,
                )
            instructions[resolution.decision_id] = parsed

        conflicting_pairs: list[tuple[str, str]] = [
            (left.change_set.change_set_id, right.change_set.change_set_id)
            for index, left in enumerate(ordered_change_sets)
            for right in ordered_change_sets[index + 1 :]
            if _change_sets_conflict(
                left.change_set, right.change_set, collision_policy=compiler_policy.collision_policy
            )
        ]

        applied: set[str] = set()
        for pair in conflicting_pairs:
            applicable = [
                resolution
                for resolution in ordered_resolutions
                if set(pair).issubset(set(resolution.competing_change_set_ids))
            ]
            if not applicable:
                return _conflict("UNRESOLVED_CONFLICT", "a detected overlap has no applicable Human resolution", *pair)
            if len(applicable) > 1:
                return _conflict(
                    "AMBIGUOUS_CONFLICT_RESOLUTION", "two applicable resolutions name one detected overlap", *pair
                )
            applied.add(applicable[0].decision_id)

        inapplicable = sorted(
            resolution.decision_id for resolution in ordered_resolutions if resolution.decision_id not in applied
        )
        if inapplicable:
            return _failed(
                "INAPPLICABLE_RESOLUTION",
                "a supplied resolution applies to no detected overlap in this selection",
                *inapplicable,
            )

        replacements = {rule.replacement_ref: rule for rule in compiler_policy.replacement_rules}
        dropped: set[str] = set()
        substitutions: list[tuple[str, tuple[NarrativeSemanticEffectKey, ...]]] = []
        for resolution in ordered_resolutions:
            instruction = instructions[resolution.decision_id]
            competitors = sorted(resolution.competing_change_set_ids)
            if instruction.kind == "KEEP":
                dropped.update(item for item in competitors if item != instruction.argument)
            elif instruction.kind == "COMBINE":
                combined = [by_id[item].change_set for item in competitors]
                for index, left in enumerate(combined):
                    for right in combined[index + 1 :]:
                        if _effect_keys_collide_across(
                            normalize_effect_keys(left.semantic_effect_keys),
                            normalize_effect_keys(right.semantic_effect_keys),
                            collision_policy=compiler_policy.collision_policy,
                        ):
                            return _conflict(
                                "COMBINED_EFFECTS_STILL_COLLIDE",
                                "a COMBINE resolution names typed effects that collide under the policy",
                                left.change_set_id,
                                right.change_set_id,
                            )
            else:
                rule = replacements.get(instruction.argument)
                if rule is None:
                    return _abstained(
                        "UNSUPPORTED_REPLACEMENT_EFFECT",
                        f"the policy declares no replacement effect {instruction.argument!r}",
                        resolution.decision_id,
                    )
                dropped.update(competitors)
                substitutions.append((resolution.decision_id, normalize_effect_keys(rule.effect_keys)))

        retained = [item for item in ordered_change_sets if item.change_set.change_set_id not in dropped]
        residual = self._residual_replacement_collision(retained, substitutions, compiler_policy)
        if residual is not None:
            return residual
        return retained, tuple(key for _, keys in substitutions for key in keys)

    def _residual_replacement_collision(
        self,
        retained: Sequence[ReviewedChangeSet],
        substitutions: Sequence[tuple[str, tuple[NarrativeSemanticEffectKey, ...]]],
        compiler_policy: CompilerPolicy,
    ) -> CompilationConflict | None:
        """Step 7 re-run over the post-resolution effective selection.

        A ``REPLACE`` substitution enters the effective key set after the original pairwise
        analysis, so it must face the same collision rule every change set faces: against each
        untouched retained change set, and against every other substitution. A substitution's
        own keys are one authored unit and are not compared with each other, exactly as one
        change set's declared keys are not."""
        for decision_id, keys in substitutions:
            for item in retained:
                if _effect_keys_collide_across(
                    keys,
                    normalize_effect_keys(item.change_set.semantic_effect_keys),
                    collision_policy=compiler_policy.collision_policy,
                ):
                    return _conflict(
                        "REPLACEMENT_EFFECTS_COLLIDE",
                        "a REPLACE resolution substitutes typed effects that collide with a retained change set",
                        decision_id,
                        item.change_set.change_set_id,
                    )
        for index, (left_decision, left_keys) in enumerate(substitutions):
            for right_decision, right_keys in substitutions[index + 1 :]:
                if _effect_keys_collide_across(
                    left_keys, right_keys, collision_policy=compiler_policy.collision_policy
                ):
                    return _conflict(
                        "REPLACEMENT_EFFECTS_COLLIDE",
                        "two REPLACE resolutions substitute typed effects that collide with each other",
                        left_decision,
                        right_decision,
                    )
        return None

    # --- §9.2 step 9 / §9.4: effect key -> M5A Canon operations ---------------

    def _map_operations(
        self,
        mutation_keys: Sequence[CanonMutationEffectKey],
        exact_canon_base: ExactCanonBase,
        compiler_policy: CompilerPolicy,
    ) -> list[CanonOperation] | _NonDeltaCompilation:
        legal_kinds = operation_kinds_for(exact_canon_base.content_schema_version)
        rules = {
            _rule_key(rule.canon_subject_kind, rule.subject_ref, rule.effect_descriptor): rule
            for rule in compiler_policy.mutation_rules
        }
        operations: list[CanonOperation] = []
        seen_ids: set[str] = set()
        for key in mutation_keys:
            rule = rules.get(_rule_key(key.canon_subject_kind, key.subject_ref, key.effect_descriptor))
            if rule is None:
                return _abstained(
                    "UNSUPPORTED_CANON_MUTATION_EFFECT",
                    f"the policy declares no rule for effect {key.effect_descriptor!r} "
                    f"on {key.canon_subject_kind} {key.subject_ref!r}",
                    key.subject_ref,
                )
            if len(rule.operations) != key.canon_operation_count:
                return _abstained(
                    "UNDERSPECIFIED_CANON_MUTATION_EFFECT",
                    f"effect promises {key.canon_operation_count} operation(s) but its rule specifies "
                    f"{len(rule.operations)}",
                    key.subject_ref,
                )
            for ordinal, template in enumerate(rule.operations):
                body = {
                    name: value for name, value in template.model_dump(mode="json").items() if name != "operation_id"
                }
                kind = body.get("kind")
                if kind not in legal_kinds:
                    return _abstained(
                        "OPERATION_KIND_ILLEGAL_FOR_CANON_SCHEMA",
                        f"operation kind {kind!r} is not legal in a "
                        f"{exact_canon_base.content_schema_version} Canon delta",
                        key.subject_ref,
                    )
                operation_id = _derive_operation_id(key, ordinal, body)
                if operation_id in seen_ids:
                    return _failed(
                        "DUPLICATE_OPERATION_ID",
                        "two mapped operations derive the same content-addressed id",
                        operation_id,
                    )
                try:
                    operation = _CANON_OPERATION_ADAPTER.validate_python({**body, "operation_id": operation_id})
                except ValidationError as error:
                    return _failed(
                        "INVALID_GENERATED_OPERATION",
                        f"a policy rule produced an invalid M5A operation: {error.error_count()} error(s)",
                        key.subject_ref,
                    )
                seen_ids.add(operation_id)
                operations.append(operation)
        return operations

    # --- §9.2 step 11 / §9.4: seal the M5A payload ----------------------------

    def _seal(
        self,
        output_identity: CompilationOutputIdentity,
        attempt: CompilationAttempt,
        exact_canon_base: ExactCanonBase,
        operations: Sequence[CanonOperation],
    ) -> CanonDeltaCompilation:
        author_decision_refs = sorted(
            {
                attempt.revision_acceptance_decision_id,
                *(selected.review_decision_id for selected in attempt.selected_change_sets),
                *attempt.conflict_resolution_decision_ids,
            }
        )
        fields = {
            "canon_delta_id": output_identity.canon_delta_id,
            "target_branch_id": attempt.work_scope.canon_branch_id,
            "base_canon_version_id": exact_canon_base.base_canon_version_id,
            "operations": [operation.model_dump(mode="json") for operation in operations],
            "source_change_set_refs": sorted({selected.change_set_id for selected in attempt.selected_change_sets}),
            "author_decision_refs": author_decision_refs,
            "validation_report_refs": [],
            "content_schema_version": exact_canon_base.content_schema_version,
            "created_at": output_identity.created_at,
            "created_by": output_identity.created_by,
        }
        try:
            payload = CanonDeltaPayload.model_validate(fields)
        except ValidationError as error:
            return _failed(
                "INVALID_CANON_DELTA_PAYLOAD",
                f"the mapped operation set does not form a valid M5A payload: {error.error_count()} error(s)",
            )
        payload_hash = compute_canon_delta_hash(payload)
        if output_identity.expected_payload_hash is not None and output_identity.expected_payload_hash != payload_hash:
            return _failed(
                "PAYLOAD_HASH_MISMATCH",
                "the caller-supplied payload hash does not equal the recomputed M5A hash",
                output_identity.canon_delta_id,
            )
        delta = CanonDelta.model_validate({**payload.model_dump(mode="json"), "payload_hash": payload_hash})
        return CompilationSucceeded(canon_delta=delta)
