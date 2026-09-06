from enum import StrEnum


class CreativeApprovalStatus(StrEnum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ArtifactCurrencyStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"


class RuntimeTaskStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CandidateSelectionStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"


class GenerationLifecycleStatus(StrEnum):
    GENERATED = "GENERATED"
    FAILED = "FAILED"


class ReadinessState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class ContentBasisType(StrEnum):
    FACTUAL = "FACTUAL"
    NARRATIVE = "NARRATIVE"
    ADAPTATION = "ADAPTATION"


class ProductionMethod(StrEnum):
    REUSE = "REUSE"
    STOCK = "STOCK"
    SCREEN_CAPTURE = "SCREEN_CAPTURE"
    DETERMINISTIC = "DETERMINISTIC"
    GENERATED_IMAGE = "GENERATED_IMAGE"
    GENERATED_VIDEO = "GENERATED_VIDEO"
    COMPOSITE = "COMPOSITE"


class ProductionBindingTarget(StrEnum):
    SCENE = "SCENE"
    SHOT = "SHOT"


class ProductionBindingRole(StrEnum):
    CHARACTER = "CHARACTER"
    LOCATION = "LOCATION"
    PROP = "PROP"
    WARDROBE = "WARDROBE"
    VOICE = "VOICE"
    STYLE = "STYLE"
    SOURCE_FOOTAGE = "SOURCE_FOOTAGE"
    OPENING_FRAME = "OPENING_FRAME"
    ENDING_FRAME = "ENDING_FRAME"
    PREVIOUS_SHOT = "PREVIOUS_SHOT"


class ProvenanceActor(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    IMPORT = "IMPORT"


class ReviewerType(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
