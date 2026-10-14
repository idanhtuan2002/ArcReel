# M8-C packet 6: shot workflow UI

**Basis:**
- [Packet 5](2026-10-14-r2-m8c-human-step-routes-packet-5.md), the human-step routes.
- The packet 4 Gate C route.
- The vertical acceptance record, which shows the chain runs in-process.
- The sponsor's 2026-10-14 approval of "frontend UI next".

## Facts

- **The UI has no way to identify a target.** Every M8-C step after frame derivation names a Shot target and its exact `TargetVersionRef`. No route lists targets or reads their binding, pair, shot task or master state.
- **Target registration has no route.** `TakeTargetRegistrationService.register` takes an exact `AdmittedScreenplayRef`, and nothing in `server/` calls it.
- **Upstream has no UI either.** The admission that produces that ref (adaptation branch, map, proposal, report, then `POST /gates/narrative-lock`) has a route but no frontend or script caller. A UI for the whole V2 adaptation chain is a separate milestone.
- **Existing UI to build on.** The frontend already has `features/spatial-analysis` (sources → frames → execution → assertions), mounted from `StudioCanvasRouter`.

## Decisions

1. **Cut.**
   - The UI starts from registered Shot targets.
   - Registration gets a route (`POST /m8/spatial/target-registrations`, body `{command_id, admitted_screenplay_ref}`), so an operator who admitted a screenplay can call it.
   - The UI does not build the admission ref.
2. **One read route**, `GET /m8/spatial/targets` (`CurrentUser`), lists each current Shot target with its state. Every field is read through the existing verified readers.
   - **Target:** ref, purpose, duration, the Scene's `location_ref`.
   - **Binding:**
     - `none` when there is no binding;
     - `stale` when the snapshot read fails;
     - otherwise the binding ID and version, the snapshot digest, the target registry version, and whether a spatial set is attached.
   - **Pair:**
     - `unavailable` without activated governance;
     - `none` when there is no current V2 decision;
     - `approved` with the binding version the pair approved.
   - **Shot:** the latest `r2_shot_generation_v1` task (ID and status).
   - **Master:** the approved `episode_video(1, target)` master version, or none.
3. **One page**, `ShotWorkflowPage`, in `features/spatial-analysis`. It lists targets, and the selected target shows one step at a time from that state:
   1. **Bind:** pick MASTER and REVERSE frames from the approved sources; reuses the frame derivation.
   2. **Review:** fetch both PNGs through the authenticated route, hash and decode them in the browser, acknowledge each, then APPROVE or REJECT with the three observations (or a reason).
   3. **Analyze:** reuses the existing spatial execution.
   4. **Promote:** pick VISIBLE assertions, preview, then promote with the returned digest.
   5. **Generate:** profile `r2-wan27-r2v-two-view@1`, using the snapshot digest and registry version from the target state.
   6. **Approve:** Gate C `r2-shots` with the finished task and an approval record.

   Each step shows the server's refusal text, and the list reloads after every write. Only the next step is enabled.
4. **Darkroom language and i18n.** The page uses the existing tokens and classes. All copy goes into zh, en and vi, except mono kickers.
5. **Not here:**
   - an adaptation or admission UI;
   - multi-episode support;
   - live provider calls (the routes are unchanged).

## Tests

- **Backend (`test_spatial_targets_route.py`):**
  - registration route: exact replay, stale ref;
  - target list state through the chain: none → bound → approved → promoted → generated → mastered;
  - a stale binding reads as `stale`;
  - without grants, pair state is `unavailable`.
- **Frontend (Vitest):**
  - the client builds the exact request bodies;
  - the page enables only the next step per state;
  - the review step hashes the fetched bytes and acknowledges with that digest;
  - a refusal shows its message.
