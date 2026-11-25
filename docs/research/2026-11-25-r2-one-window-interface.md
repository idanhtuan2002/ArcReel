# One window for every part (sponsor question 2026-11-25: manage everything inside DramaClaw's UI?)

Labels: **FACT**, **INFER**.

## Facts

- DramaClaw's web (`:8080`) sends `X-Frame-Options: DENY` and `Content-Security-Policy: default-src 'self'; …`
  (measured with curl): it cannot be shown inside another page, and its own pages cannot frame other origins.
- DramaClaw's only iframe is the canvas HTML-artifact node: a sandboxed `srcDoc` preview of generated HTML
  (`features/html-artifacts/HtmlArtifactNode.tsx`), not a host for other apps. No plugin/menu extension point was found
  in `frontend/src` (no external-link or nav-item configuration).
- Backlot (`:4750`), our console (`:8790`) and NewAPI (`:3000`) send no framing headers.
- The parts today: DramaClaw (films, canvas, settings), control page (runs, catalog, finish/review), Backlot
  (OpenMontage), NewAPI (models and keys); huohuo joins in M3.

## Options

| | What | Donor change | Upkeep | Result |
|---|---|---|---|---|
| A | Same tab: every link opens in the same window; the control page is the start page | none | none | one window, back/forward between apps |
| B | One shell (control page) with a left menu; DramaClaw, Backlot, NewAPI shown inside it through a local reverse proxy on one origin that drops DramaClaw's `X-Frame-Options`/`frame-ancestors` for 127.0.0.1 only | none (proxy config) | small: proxy routes | one window, all parts side by side; DramaClaw's clickjacking guard is off for the local proxy origin |
| C | Inside DramaClaw: add menu entries and pages (runs, finish/review, OpenMontage, models) to DramaClaw's React frontend, rebuild its image | yes (frontend fork) | each DramaClaw upgrade: re-apply, rebuild, retest | literally "in DramaClaw's UI"; against GOAL rule 2 (donor whole) unless the sponsor accepts the fork |

INFER: B gives the single centred interface without forking a donor; C matches the wording but adds a fork to every
upgrade (DramaClaw moved 2.0.2 → 2.1.3 in one day of this project).
