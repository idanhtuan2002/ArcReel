# R2.4 — Open Decisions

These items do **not** reopen frozen architecture. They are implementation, provider-qualification, hardening, or deferred-feature decisions.

## R2-OPEN-001 — Physical SQL/ORM mapping for R2 custom authority contracts

**Class:** `IMPLEMENTATION_DETAIL`  
**Architecture reopen:** `FALSE`  
**Resolve in:** R2 implementation planning / first host fork milestone

**Constraints:**
- must preserve frozen contract ownership
- PostgreSQL baseline
- no parallel artifact registry

## R2-OPEN-002 — Exact R2 extension seam inside ArcReel Artifact Manifest

**Class:** `IMPLEMENTATION_DETAIL`  
**Architecture reopen:** `FALSE`  
**Resolve in:** R2 host fork milestone

**Constraints:**
- ContentBasis/direct dependency edges must be preserved
- no provider fields in ShotSpec

## R2-OPEN-003 — R2-HOST-001 implementation choice

**Class:** `PRODUCTION_HARDENING`  
**Architecture reopen:** `FALSE`  
**Resolve in:** R2.5 / host hardening implementation

**Constraints:**
- persist execution identity preferred
- temporary config lock acceptable

## R2-OPEN-004 — Provider qualification matrix and default provider ranking

**Class:** `PROVIDER_QUALIFICATION`  
**Architecture reopen:** `FALSE`  
**Resolve in:** post-core provider qualification

**Constraints:**
- MethodDecision remains provider-neutral
- CapabilityRegistry is sole business-facing catalog

## R2-OPEN-005 — Physical representation of branch overlays/resolved Canon views

**Class:** `IMPLEMENTATION_DETAIL`  
**Architecture reopen:** `FALSE`  
**Resolve in:** Canon/Epistemic milestone

**Constraints:**
- parent-linked immutable base
- auditable overlay
- no silent parent mutation

## R2-OPEN-006 — Advanced Director World / spatial planning activation

**Class:** `DEFERRED_FEATURE`  
**Architecture reopen:** `FALSE`  
**Resolve in:** advanced creative workbench phase

**Constraints:**
- must remain production-planning layer, not Canon authority


## R2.5 resolution note

`R2-OPEN-003` is now constrained by frozen H1: preferred fix is persisted execution identity; temporary active-task configuration lock is permitted. Exact code location remains an implementation detail.
