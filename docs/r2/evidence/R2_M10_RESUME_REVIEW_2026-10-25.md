Preliminary read-only gap review of9a58b60206b6191f5deb43f844fcf0c1ec78d068.
Not a normative design review and not an acceptance record.

Two confirmed design defects and one contract risk:
1. New-run/profile blanket invalidation contradicts HISTORICAL_ONLY and could let an evidence producer revoke Human disposition. FIXED in the proposed delta: remove active-run head, preserve new-run neutrality, add explicit authority/transition matrix and required concurrency tests.
2. serialized_artifacts opens its own transaction and creates rows; it cannot compose after caller command guard. FIXED: name lock_current_master_rows and verify_masters on same caller session, reject absent promoted head; keep full sorted closure and re-resolve changed lock set.
3. Fictional applicability must not omit a declared required factual slot. FIXED: a published policy may have no factual requirement; an existing required slot requires a bound allowed inapplicability observation, never runtime omission or an unavailable-authority excuse.

Parent additionally corrected original §5 command/receipt tuple to include project_name, matching the existing scope invariant. A single repair pass was made; changed candidate has not had normative review. Full implementation proofs remain outstanding.
