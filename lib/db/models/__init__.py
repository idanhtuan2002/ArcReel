"""ORM model exports."""

from lib.db.models.adaptation import (
    AdaptationBranchModel,
    AdaptationDecisionModel,
    AdaptationEvaluationFindingModel,
    AdaptationEvaluationReportModel,
    AdaptationHeadModel,
    AdaptationMapEntryModel,
    AdaptationMapModel,
    AdaptationMapProfileAnalysisRefModel,
    AdaptationProfileSidecarModel,
    AdaptationScreenplayAdmissionModel,
    AdaptationScreenplayModel,
    AdaptationScreenplayProfileAnalysisRefModel,
    AdaptationScreenplaySceneModel,
)
from lib.db.models.advanced_creative import (
    M8CandidateHeadModel,
    M8CandidateRevisionModel,
    M8CommandReceiptModel,
    M8PromotionAuthorizationModel,
    M8PromotionPreviewModel,
    M8PromotionReceiptModel,
)
from lib.db.models.agent_credential import AgentAnthropicCredential
from lib.db.models.api_call import ApiCall
from lib.db.models.api_key import ApiKey
from lib.db.models.asset import Asset, AssetDerivative
from lib.db.models.budget_reservation import BudgetReservationModel, BudgetScopeModel
from lib.db.models.canon import (
    CanonBranchModel,
    CanonDeltaModel,
    CanonResolvedProjectionModel,
    CanonVersionModel,
)
from lib.db.models.config import ProviderConfig, SystemSetting
from lib.db.models.credential import ProviderCredential
from lib.db.models.custom_endpoint import CustomEndpoint
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel
from lib.db.models.gates import FinalCutReceiptModel, GreenlightDecisionModel, PublishApprovalDecisionModel
from lib.db.models.host_hardening import (
    AttemptIntegrityIncidentModel,
    BackupSetMediaRefModel,
    BackupSetModel,
    CandidateObjectModel,
    CommandReceiptModel,
    ExecutionAttemptModel,
    MasterAuthorityModel,
    MasterHeadVersionModel,
    OperatorResolutionReceiptModel,
    ProjectEventModel,
    PromotionReceiptModel,
    ProviderObservationModel,
)
from lib.db.models.narrative_lifecycle import (
    NarrativeChangeSetModel,
    NarrativeDraftCandidateModel,
    NarrativeExtractionAttemptModel,
    NarrativeExtractionResultChangeSetModel,
    NarrativeExtractionResultModel,
    NarrativeRevisionModel,
)
from lib.db.models.narrative_plan import NarrativePlanModel, NarrativePlanVersionModel
from lib.db.models.production_target import (
    ProductionTargetCommandModel,
    ProductionTargetHeadModel,
    ProductionTargetVersionModel,
)
from lib.db.models.session import AgentSession
from lib.db.models.session_event import AgentSessionEventLogEntry
from lib.db.models.session_message_link import AgentSessionUserMessageLink
from lib.db.models.spatial_source import SpatialFrameReceiptModel
from lib.db.models.task import BatchTask, GenerationBatch, Task, WorkerLease
from lib.db.models.user import User

__all__ = [
    "AdaptationBranchModel",
    "AdaptationDecisionModel",
    "AdaptationEvaluationFindingModel",
    "AdaptationEvaluationReportModel",
    "AdaptationHeadModel",
    "AdaptationMapEntryModel",
    "AdaptationMapModel",
    "AdaptationMapProfileAnalysisRefModel",
    "AdaptationProfileSidecarModel",
    "AdaptationScreenplayAdmissionModel",
    "AdaptationScreenplayModel",
    "AdaptationScreenplayProfileAnalysisRefModel",
    "AdaptationScreenplaySceneModel",
    "AgentAnthropicCredential",
    "AgentSession",
    "AgentSessionEventLogEntry",
    "AgentSessionUserMessageLink",
    "ApiCall",
    "ApiKey",
    "Asset",
    "AssetDerivative",
    "AttemptIntegrityIncidentModel",
    "BackupSetMediaRefModel",
    "BackupSetModel",
    "BatchTask",
    "BudgetReservationModel",
    "BudgetScopeModel",
    "CandidateObjectModel",
    "CanonBranchModel",
    "CanonDeltaModel",
    "CanonResolvedProjectionModel",
    "CanonVersionModel",
    "CommandReceiptModel",
    "CustomEndpoint",
    "CustomProvider",
    "CustomProviderModel",
    "ExecutionAttemptModel",
    "FinalCutReceiptModel",
    "GenerationBatch",
    "GreenlightDecisionModel",
    "M8CandidateHeadModel",
    "M8CandidateRevisionModel",
    "M8CommandReceiptModel",
    "M8PromotionAuthorizationModel",
    "M8PromotionPreviewModel",
    "M8PromotionReceiptModel",
    "MasterAuthorityModel",
    "MasterHeadVersionModel",
    "NarrativeChangeSetModel",
    "NarrativeDraftCandidateModel",
    "NarrativeExtractionAttemptModel",
    "NarrativeExtractionResultChangeSetModel",
    "NarrativeExtractionResultModel",
    "NarrativePlanModel",
    "NarrativePlanVersionModel",
    "NarrativeRevisionModel",
    "OperatorResolutionReceiptModel",
    "ProductionTargetCommandModel",
    "ProductionTargetHeadModel",
    "ProductionTargetVersionModel",
    "ProjectEventModel",
    "PromotionReceiptModel",
    "ProviderConfig",
    "ProviderCredential",
    "ProviderObservationModel",
    "PublishApprovalDecisionModel",
    "SpatialFrameReceiptModel",
    "SystemSetting",
    "Task",
    "User",
    "WorkerLease",
    "register_models",
]


def register_models() -> None:
    """把本包内全部 ORM 模型登记到 ``Base.metadata``。

    登记发生在 import 本模块时（模型类定义即注册），本函数不做额外工作；
    调用它是为了让「因副作用而 import」在调用点显式可见。
    """
