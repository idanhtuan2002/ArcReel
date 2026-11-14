---
status: accepted
---

# Every shot of a scene carries the scene's look

Decided 2026-11-13 by the main agent (craft program P0-3, `docs/research/2026-11-13-r2-film-craft-quality.md`).

Shots were lit one by one: each storyboard's `composition.lighting` was written alone, so two shots of the same room could differ in time of day, light direction and colour.

1. **A scene look.** A scene runs from a script-plan entry marked `segment_break` (or the episode's first entry) to the entry before the next break. Narration prompt authoring writes one `SceneLook` per scene it rewrites the start of (`time_of_day`, `key_light` with source, direction, quality and Kelvin, a 2–4 colour hex `palette`, `palette_note` saying where the colours fall, `mood`), keyed by the scene's first segment id in a keyed schema like the segments. A scene whose start is kept keeps the look its shots carry, and the prompt shows that look read-only to the rewritten shots of that scene.
2. **Copied into each shot.** Merging copies the look into every shot's `image_prompt.look` (hidden from the per-shot output schema). The storyboard prompt renders it as a `Scene_Look` block after the composition, so every shot of the scene is generated under the same light and colours; a changed look changes the storyboard's visual basis and the storyboard is regenerated. Shots without a look project exactly as before.
3. The prompt asks the shot's `composition.lighting` to stay with the scene's key light (same source, direction and colour temperature), and the looks of successive scenes to follow the episode's emotional arc, so the episode reads like a colour script.

This follows Calliope's continuity ledger (`calliope-backend/src/calliope/agent/continuity.py`: a locked lighting and style overview plus per-shot light state), adapted to our per-scene keyed schema; BFL's FLUX.2 guide names `lighting` and `color_palette` as the prompt keys for this. Drama scenes, a critic checking each shot against its look (Calliope's nine-bucket critic) and a numeric consistency check are later items (P1-9, P1-12).

Amended after the release review (M4): when an incremental authoring rewrites a scene's first shot and writes a new look, the kept shots of that scene take the new look too, so one scene never carries two looks.
