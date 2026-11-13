# Face repair by a multi-reference edit (identity ID-6), 2026-11-14

Question: can a storyboard that shows the wrong person be repaired in place, keeping its composition, instead of being regenerated?

Method: local FLUX.2 klein 4B reference workflow, reference 1 = the look-alike frame of continuity corpus 2, reference 2 = the right character's sheet; prompt "Edit image 1: keep its composition, pose, clothing, background, lighting and framing exactly the same. Only replace the person's face and hair with the face and hair of <name> from image 2, matching the light of image 1." Seed 7. Measured: ArcFace cosine to the right sheet before and after (face server of ADR-0151), and composition kept as the correlation of the two frames' 144×256 greyscale. Script `face_repair.py.txt`; `before_after.jpg` shows each frame then its edit (s4-2, s5-3, s1-0, s2-1).

| Case | cosine before | after | composition kept |
|---|---|---|---|
| s4-2 | −0.005 | 0.580 | 0.952 |
| s5-3 | 0.177 | 0.467 | 0.903 |
| s1-0 | −0.033 | 0.072 | 0.864 |
| s2-1 | 0.228 | 0.293 | 0.256 |

Findings: two of four repairs land (identity well above the 0.29 same-person mark with the frame kept); one barely moves; one redraws the frame. An acceptance rule "cosine after ≥ 0.29 and composition ≥ 0.85" keeps exactly the two good ones, so a repair must always be checked independently and dropped when it fails.

Not wired in yet, and why: a repaired version is made from other references (the frame and the sheet) than the script's storyboard request, so its visual basis differs from the one the workflow expects and artifact currency would mark it stale and regenerate it. Wiring repair in needs a decision on how a repaired version stays current (for example, a repair recorded as a derived version of a current storyboard), and the trial film's numbers on how often the best-of-2 choice (ADR-0151) still shows the wrong person.
