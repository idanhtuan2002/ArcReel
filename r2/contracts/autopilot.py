"""A project's standing autopilot delegation (ADR-0124): one append-only version per Showrunner decision."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from r2.contracts.automation import AutomationContract, AutomationMode, Digest, ExactIdentity, PositiveInt
from r2.contracts.fingerprints import canonical_json_bytes

AUTOPILOT_DELEGATION_SCHEMA = "r2.autopilot-delegation.v1"

_Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class StoryAutopilot(AutomationContract):
    """A story project writes its book part after part: part 1 from ``idea``, each next part continuing it."""

    idea: _Text
    book_chapters: Annotated[int, Field(ge=6, le=120)]
    #: What a continuation is asked to do; a continuation run needs an instruction.
    direction: _Text = "Continue the book from where the previous part ended, following the book plan."


class FilmAutopilot(AutomationContract):
    """A film project films its linked story, this many episodes per run."""

    episodes_per_run: Annotated[int, Field(ge=1, le=12)] = 1


class AutopilotDelegation(AutomationContract):
    schema_id: Literal["r2.autopilot-delegation.v1"] = AUTOPILOT_DELEGATION_SCHEMA
    user_id: ExactIdentity
    project_name: ExactIdentity
    version: PositiveInt
    state: Literal["ENABLED", "DISABLED"]
    kind: Literal["story", "film"]
    issuer_id: ExactIdentity
    command_id: ExactIdentity
    #: The Showrunner grant event the delegation was given under (a project's or the workspace's, ADR-0123).
    parent_sequence: PositiveInt
    parent_event_digest: Digest
    mode: AutomationMode
    policy_digest: Digest
    story: StoryAutopilot | None = None
    film: FilmAutopilot | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def parameters_match_kind(self) -> Self:
        if self.state == "ENABLED" and (self.story is not None) != (self.kind == "story"):
            raise ValueError("a story delegation carries story parameters")
        if self.state == "ENABLED" and (self.film is not None) != (self.kind == "film"):
            raise ValueError("a film delegation carries film parameters")
        return self

    def digest(self) -> str:
        body = {"domain": AUTOPILOT_DELEGATION_SCHEMA, "body": self.model_dump(mode="json")}
        return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def autopilot_command_prefix(delegation: AutopilotDelegation) -> str:
    """Every start command of the delegation begins with this."""
    return f"autopilot:{delegation.digest().removeprefix('sha256:')[:32]}:"


def autopilot_command_id(delegation: AutopilotDelegation, ordinal: int, *, part: int | None = None) -> str:
    """The start command of the delegation's ``ordinal``-th run (and, for a story, the book part it writes); a
    replayed scan starts the same run."""
    return autopilot_command_prefix(delegation) + str(ordinal) + ("" if part is None else f":p{part}")


__all__ = [
    "AUTOPILOT_DELEGATION_SCHEMA",
    "AutopilotDelegation",
    "FilmAutopilot",
    "StoryAutopilot",
    "autopilot_command_id",
    "autopilot_command_prefix",
]
