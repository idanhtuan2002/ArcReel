# BytePlus Seedance 2.0 and Seedream 4.x official prompt rules (craft program P2-14), 2026-11-14

The official ModelArk guides are JavaScript pages that WebFetch could not read (`2026-11-13-r2-film-craft-quality.md`, Unknowns). Rendered here with headless Chrome (`google-chrome --headless=new --dump-dom`) on 2026-11-14:
`https://docs.byteplus.com/en/docs/ModelArk/seedance-2-0-prompt-guide` and `https://docs.byteplus.com/en/docs/modelark/seedream-4-0-5-0-prompt-guide`. FACT = stated on the page.

## Seedance 2.0 (video, joint audio)
- FACT: "Advanced prompt formula: precise subject + action details + scene/environment + lighting & color tone + camera movement + visual style + image quality + constraints" — first who does what, then where and what atmosphere, then how to shoot, then style, quality and constraints.
- FACT: a subject is defined by "2–3 clear and stable static features (such as clothing, hairstyle, appearance, or category)"; several subjects get unique, stable labels used consistently; every mention binds the subject to its asset (`Zhang San@Image 1`), also when an asset library id is used.
- FACT: express spatial relationships through reference images first rather than complex text.
- FACT: for a complex video write a timeline storyboard, "Shot 1 / Shot 2 / Shot 3", each with camera move or transition, subject action and expression, position, and sound; do not impose per-shot seconds ("support for precise timing (such as 0–3 seconds) is unstable").
- FACT: actions name body parts and degree ("slowly raise a hand"), prefer "slow, gentle, coherent subtle movements", state transitions between actions, and externalize emotion as visible behaviour (the guide tabulates sad, happy, anxious, angry, relieved).
- FACT: standard camera terms are understood; "Try to specify only 1 type of camera movement in a single shot."
- FACT: constraints are stated positively: "keep it subtitle-free", "do not generate a logo", "do not generate a watermark".
- FACT: for edit or extend tasks refer to the video directly, not "reference video N", or the task is taken as a reference task.

## Seedream 4.0–4.5 (image)
- FACT: describe "subject + action + environment" in coherent natural language, not keyword lists; concise, precise prompts beat stacked ornate vocabulary.
- FACT: state the application scenario and the style explicitly; put text to render in double quotes.
- FACT: for editing, name the target precisely (no vague pronouns) and say what stays unchanged.
- FACT: with reference images, say which elements are extracted and kept (character design, material, style) and then describe the generated scene.

## What this means for us (inference)
- Our visual layer already follows most of these rules (concrete subject first, physical verbs, slow single-thread actions, one slow camera move: ADR-0144; emotions as visible details in the scene guide). They confirm the move limits of ADR-0144 from the vendor's side.
- When a Seedance route is qualified, the request builder should: bind each character to its reference with a stable label at every mention (our cast block plus `@Image N`), render a multi-shot unit as "Shot 1 / Shot 2" without seconds, and turn our negative tail into positive constraints. For Seedream, the cast block already gives 2–3 stable features; the reference-image clause should say "keep the character design from Image N".
- No change is made now: every cloud media route is unqualified in production.
