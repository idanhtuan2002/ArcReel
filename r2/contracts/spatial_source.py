"""Versioned identity and receipt shapes for derived M8-C source frames."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from r2.contracts.advanced_creative import M8ContractModel, Sha256Digest

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]
FrameCandidateId = Annotated[str, StringConstraints(pattern=r"^m8f:[0-9a-f]{64}$")]


class FrameIdentityV1(M8ContractModel):
    user_id: NonBlank
    project_name: NonBlank
    parent_artifact_key: NonBlank
    parent_master_version: int = Field(ge=1)
    parent_candidate_id: NonBlank
    parent_content_digest: Sha256Digest
    decoded_frame_index: int = Field(ge=0)
    recipe_version: NonBlank
    decoder_identity: NonBlank
    frame_content_digest: Sha256Digest

    @property
    def candidate_id(self) -> str:
        envelope = {
            "domain": "r2.m8.spatial.frame.identity.v1",
            "canonical_version": "1",
            "body": self.model_dump(mode="json"),
        }
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return "m8f:" + hashlib.sha256(canonical).hexdigest()


class FrameDerivationReceiptV1(M8ContractModel):
    identity: FrameIdentityV1
    frame_candidate_id: FrameCandidateId
    frame_byte_size: int = Field(gt=0)
    frame_probe_digest: Sha256Digest
    created_at: AwareDatetime
    command_digest: Sha256Digest

    @model_validator(mode="after")
    def matches_identity(self) -> Self:
        if self.frame_candidate_id != self.identity.candidate_id:
            raise ValueError("frame candidate id does not match identity digest")
        return self
