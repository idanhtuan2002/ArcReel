"""``ASSET_ANALYSIS``: the whole source's character/scene/prop inventory through the bounded schema executor.

The status owner names the scope and the source revision to analyze; the ``text_asset_inventory`` task extracts
against exactly that revision and completes the inventory atomically. The step's evidence is the source revision
the inventory completed against, which every later text stage pins.
"""

from __future__ import annotations

from lib.workflow_state import WorkflowStatus
from r2.contracts.automation import DispatchIntent, OwnerReceipt, RunStage
from server.production_run.owner_support import OwnerBlocked
from server.production_run.text_adapter import WorkflowStageAdapter, revision_receipt
from server.tool_runtime import TEXT_ASSET_INVENTORY


class AssetsAdapter(WorkflowStageAdapter):
    owner = "asset-inventory"
    stage = RunStage.ASSET_ANALYSIS
    first_rank = 1
    done_rank = 1
    per_target = False
    calls_per_unit = 2
    seconds_per_unit = 900

    async def _act(self, intent: DispatchIntent, subject: str, status: WorkflowStatus, episode: int | None) -> bool:
        args = status.next_action.args
        revision = args.get("expected_source_revision")
        if not isinstance(revision, str):
            raise OwnerBlocked("WORKFLOW_SOURCE_UNAVAILABLE")
        return await self._submit_once(
            intent,
            subject,
            sub_key=f"assets:{revision}",
            task_type=TEXT_ASSET_INVENTORY,
            resource_id="asset-inventory",
            payload={"scope": args.get("scope"), "expected_source_revision": revision},
        )

    def _evidence(self, intent: DispatchIntent, status: WorkflowStatus, episode: int | None) -> OwnerReceipt:
        inventory = self._project(intent.scope.project_name).get("workflow", {}).get("asset_inventory")
        revision = inventory.get("source_revision") if isinstance(inventory, dict) else None
        if not isinstance(revision, str) or revision != status.source_revision:
            raise OwnerBlocked("OWNER_OUTPUT_MISSING")
        return revision_receipt(self.owner, "asset-inventory", revision)


__all__ = ["AssetsAdapter"]
