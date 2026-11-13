---
status: accepted
---

# Shots keep their screen direction within a scene

Decided 2026-11-14 by the main agent (craft program P1-12).

The continuity judge (ADR-0134) already checks `screen_direction` (the 180-degree rule) and `eyeline` against the previous shot of the scene, but the visual layer never wrote where characters stand or which way they face, so the generator chose sides freely and the judge could only reject.

The scene writing guide (narration and drama prompt authoring) now asks for blocking: when a character first enters a scene, the shot says whether they are on the left, centre or right of frame, which way they face and what they look at; later shots of the scene keep that side and facing; in a two-person exchange one stands left facing right and the other right facing left, and reverse shots keep the relation; a new scene may restage. Definitions follow the MIT film lexicon (180-degree rule, eyeline match, shot/reverse shot). No new field: positions are part of the shot's visible description, which the storyboard prompt and the judge already read.
