---
status: accepted
---

# A storyboard lit unlike its scene is made again

Decided 2026-11-13 by the main agent (craft program P1-9).

Shots of a scene share one look (ADR-0141), but a generator can still render one of them in another light or colour cast. Vision-language models read lighting conditions poorly (ShotBench, arXiv 2506.21356: at most ~49 % on lighting condition), so the check is numeric.

1. For each scene whose shots carry a scene look, the MEDIA owner measures every storyboard's mean luminance (0–255) and warmth ((mean red − mean blue) / 255) and compares them with the scene's medians. A shot more than 40 luminance or 0.12 warmth away is an outlier; scenes of fewer than three shots have no reliable median and are not judged.
2. When no storyboard fails its own technical check, each outlier that has not been made again yet is regenerated once through the existing bounded unit redo (`unit:storyboards:<id>`). A remade shot is accepted as it comes back: the check never loops.
3. Shots without a scene look (older scripts, other skeletons) are not grouped.

The thresholds are first estimates; the trial film's measurements will show whether they catch real drift without remaking deliberate changes (a lamp switched off inside a scene).

Amended after the release review (M2): a storyboard the best-of-N judge already chose (ADR-0151) is not remade by this check; the judge's pick wins.
