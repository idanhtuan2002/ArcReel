"""Sidecars of typed spatial promotion; every read rehashes the V2 body against its base row."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_pair import SpatialPreviewBindingModel, SpatialPromotionResultModel
from r2.contracts.advanced_creative import PromotionPreview, PromotionReceipt
from r2.contracts.spatial_promotion import (
    SpatialPreviewBindingV2,
    SpatialPromotionPreviewV2,
    SpatialPromotionReceiptV2,
    SpatialPromotionResultV2,
)
from r2.production_binding.spatial_promotion import spatial_preview_v2_digest, spatial_receipt_v2_digest


class SpatialPromotionIntegrityError(ValueError):
    """A binding-target preview or receipt and its sidecar do not verify together."""


class SpatialPromotionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def stage_preview_binding(
        self, *, user_id: str, base_preview: PromotionPreview, binding: SpatialPreviewBindingV2
    ) -> SpatialPromotionPreviewV2:
        preview = SpatialPromotionPreviewV2(schema_version="2", base_preview=base_preview, binding=binding)
        digest = spatial_preview_v2_digest(preview.model_dump(mode="json"))
        self.session.add(
            SpatialPreviewBindingModel(
                user_id=user_id,
                project_name=base_preview.project_name,
                preview_id=base_preview.preview_id,
                binding_id=binding.binding_id,
                expected_binding_version=binding.expected_binding_version,
                binding_json=binding.model_dump(mode="json"),
                preview_v2_digest=digest,
            )
        )
        await self.session.flush()
        return preview

    async def get_preview_verified(
        self, *, user_id: str, base_preview: PromotionPreview
    ) -> tuple[SpatialPromotionPreviewV2, str]:
        row = await self.session.get(SpatialPreviewBindingModel, base_preview.preview_id)
        if row is None or (row.user_id, row.project_name) != (user_id, base_preview.project_name):
            raise SpatialPromotionIntegrityError("the binding-target preview has no spatial sidecar")
        try:
            preview = SpatialPromotionPreviewV2(
                schema_version="2",
                base_preview=base_preview,
                binding=SpatialPreviewBindingV2.model_validate(row.binding_json),
            )
        except (ValidationError, ValueError) as exc:
            raise SpatialPromotionIntegrityError("the spatial preview sidecar is malformed") from exc
        digest = spatial_preview_v2_digest(preview.model_dump(mode="json"))
        if digest != row.preview_v2_digest or (row.binding_id, row.expected_binding_version) != (
            preview.binding.binding_id,
            preview.binding.expected_binding_version,
        ):
            raise SpatialPromotionIntegrityError("the spatial preview differs from its stored digest")
        return preview, digest

    async def stage_result(
        self, *, user_id: str, base_receipt: PromotionReceipt, result: SpatialPromotionResultV2
    ) -> SpatialPromotionReceiptV2:
        receipt = SpatialPromotionReceiptV2(schema_version="2", base_receipt=base_receipt, result=result)
        self.session.add(
            SpatialPromotionResultModel(
                user_id=user_id,
                project_name=base_receipt.project_name,
                receipt_id=base_receipt.receipt_id,
                binding_id=result.binding_id,
                binding_version=result.binding_version,
                set_id=result.constraint_set_id,
                result_json=result.model_dump(mode="json"),
                receipt_v2_digest=spatial_receipt_v2_digest(receipt.model_dump(mode="json")),
            )
        )
        await self.session.flush()
        return receipt

    async def get_receipt_verified(self, *, user_id: str, base_receipt: PromotionReceipt) -> SpatialPromotionReceiptV2:
        row = await self.session.get(SpatialPromotionResultModel, base_receipt.receipt_id)
        if row is None or (row.user_id, row.project_name) != (user_id, base_receipt.project_name):
            raise SpatialPromotionIntegrityError("the binding-target receipt has no spatial result")
        try:
            receipt = SpatialPromotionReceiptV2(
                schema_version="2",
                base_receipt=base_receipt,
                result=SpatialPromotionResultV2.model_validate(row.result_json),
            )
        except (ValidationError, ValueError) as exc:
            raise SpatialPromotionIntegrityError("the spatial result sidecar is malformed") from exc
        if spatial_receipt_v2_digest(receipt.model_dump(mode="json")) != row.receipt_v2_digest or (
            row.binding_id,
            row.binding_version,
            row.set_id,
        ) != (receipt.result.binding_id, receipt.result.binding_version, receipt.result.constraint_set_id):
            raise SpatialPromotionIntegrityError("the spatial receipt differs from its stored digest")
        return receipt


__all__ = ["SpatialPromotionIntegrityError", "SpatialPromotionRepository"]
