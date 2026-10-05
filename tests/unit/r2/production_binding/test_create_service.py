"""The LOCATION command derives custody claims from verified frame receipts."""

from __future__ import annotations

from datetime import UTC, datetime

from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.spatial_source import FrameDerivationReceiptV1, FrameIdentityV1
from server.services.location_binding import _claim_from_verified_frame
from server.services.spatial_frame_reader import VerifiedSpatialFrame


def test_frame_claim_uses_verified_receipt_identity_and_digest() -> None:
    identity = FrameIdentityV1(
        user_id="u1",
        project_name="demo",
        parent_artifact_key="video:room-a",
        parent_master_version=2,
        parent_candidate_id="candidate-video-a",
        parent_content_digest="sha256:" + "a" * 64,
        decoded_frame_index=7,
        recipe_version="frame-v1",
        decoder_identity="ffmpeg-7",
        frame_content_digest="sha256:" + "b" * 64,
    )
    receipt = FrameDerivationReceiptV1(
        identity=identity,
        frame_candidate_id=identity.candidate_id,
        frame_byte_size=128,
        frame_probe_digest="sha256:" + "c" * 64,
        created_at=datetime.now(UTC),
        command_digest="sha256:" + "d" * 64,
    )
    verified = VerifiedSpatialFrame(receipt=receipt, receipt_digest=_receipt_digest(receipt), png_bytes=b"PNG")
    claim = _claim_from_verified_frame(verified)
    assert claim.receipt_id == identity.candidate_id
    assert claim.receipt_digest == _receipt_digest(receipt)
    assert claim.frame_candidate_id == identity.candidate_id
    assert claim.frame_content_digest == identity.frame_content_digest
    assert claim.parent_artifact_key == identity.parent_artifact_key
    assert claim.parent_master_version == identity.parent_master_version
    assert claim.parent_content_digest == identity.parent_content_digest
    assert claim.decoded_frame_index == identity.decoded_frame_index
    assert claim.decoder_identity == identity.decoder_identity
