# Model licences in the film pipeline, and identity-model alternatives to FLUX.1-dev (2026-11-14)

Asked by the sponsor after the craft and identity program: record what we learned about the candidate models and their licence limits, and replace the DreamO bake-off (ID-7) with Qwen-Image-Edit-2511.

Scope note: the sponsor's standing rule is that licence never blocks a design, review or acceptance decision (`CLAUDE.md`, "License 不在范围内"). This file only states the facts so the sponsor can decide what a commercial release needs. Sources were read on 2026-11-14 (official model cards, repository READMEs and licence files; the local clones' own files where noted). FACT = stated by the source; INFERENCE = ours.

## 1. Models the pipeline runs today

| Use | Model | Code licence | Weights / model licence | Commercial use of the model | Source |
|---|---|---|---|---|---|
| Storyboards (local) | FLUX.2 [klein] 4B (GGUF Q4 in ComfyUI) | — | Apache-2.0: "Open weights available for commercial use under the Apache 2.0 license." The 9B variants are "under a non-commercial license". Not gated. | Allowed (4B) | https://huggingface.co/black-forest-labs/FLUX.2-klein-4B |
| Image tool | ComfyUI | GPL-3.0 | — | Allowed (copyleft on the tool's own code) | local `~/comfyui/LICENSE` |
| Music bed (ADR-0143) | ACE-Step 1.5 | MIT ("This project is licensed under MIT") | not separately stated in the README | Allowed per the stated MIT licence | local `/mnt/arcreel/D/ArcReel/ace-step/LICENSE`, README §License |
| Ambience (ADR-0150) | MMAudio `large_44k_v2` | MIT | **CC-BY-NC 4.0** ("The checkpoints are released on Hugging Face under the CC-BY-NC 4.0 license"); README also: "We do not guarantee that the pre-trained models are suitable for commercial use." | **Not allowed** (non-commercial) | local `/mnt/arcreel/D/ArcReel/mmaudio/README.md` lines 155, 182–183 |
| Face-identity judge (ADR-0151) | InsightFace `buffalo_l` | MIT ("no limitation for both academic and commercial usage") | "ALL models are available for non-commercial research purposes only"; update 2025-11-24: for `buffalo_l` "please contact recognition-oss-pack@insightface.ai for licensing" | **Not allowed** without a licence from InsightFace | https://github.com/deepinsight/insightface , `/tree/master/model_zoo` |
| Narration TTS | VieNeu-TTS v3 Turbo | Apache-2.0 (repository) | README: "License: Apache 2.0 (Free to use)"; a separate licence on the v3 Turbo weights was not found | Allowed per the README (weights licence not separately verified) | local `~/VieNeu-TTS/LICENSE`, README §6 |

INFERENCE: two components of the release candidate (ambience, face judge) use non-commercial weights. Both are optional at run time (no `ARCREEL_AMBIENCE_URL` → no ambience; no `ARCREEL_FACE_ID_URL` → one storyboard per shot), so a commercial deployment can switch them off by environment without code changes, or replace them (§3).

## 2. Identity models considered for ID-7

| Model | Licence | Gated on Hugging Face | Size / VRAM (stated) | Identity features (stated) | Source |
|---|---|---|---|---|---|
| FLUX.1 [dev] | "FLUX.1 [dev] Non-Commercial License v1.1.1": weights only for non-commercial purposes (§2(a), 2(b)); §4(a) forbids "any commercial or production purposes"; outputs: "You may use Output for any purpose (including for commercial purposes)" (§2(d)) except training a competing model, with content filtering or review (§2(e)); §4(a) also names "any data produced by the FLUX.1 [dev] Model", a tension the text does not resolve | Yes ("agree to share your Hugging Face information") | 12B | base for DreamO, PuLID-FLUX, InfiniteYou, UNO (earlier research) | https://huggingface.co/black-forest-labs/FLUX.1-dev , `LICENSE.md` |
| FLUX.1 [schnell] | Apache-2.0 ("can be used for personal, scientific, and commercial purposes") | Yes | 12B | none of the identity adapters target it (unverified for DreamO) | https://huggingface.co/black-forest-labs/FLUX.1-schnell |
| DreamO | code Apache-2.0; base model not named in the README (earlier research: FLUX.1) | — | README: Nunchaku + CPU offload "24 GB → 6.5 GB" | ID + IP + try-on conditions | https://github.com/bytedance/DreamO |
| **Qwen-Image-Edit-2511** | Apache-2.0 | No | 20B | "Improved Multi-Person Consistency" (fuses separate person images into one group shot) | https://huggingface.co/Qwen/Qwen-Image-Edit-2511 |
| Qwen-Image-Edit-2509 | Apache-2.0 | No | 20B | "Optimal performance … 1 to 3 input images"; person+person, "Better preservation of facial identity" | https://huggingface.co/Qwen/Qwen-Image-Edit-2509 |
| OmniGen2 | code Apache-2.0; weights licence not verified | — | ~17 GB native; model offload ~−50 %; sequential offload < 3 GB, "significantly slower" | multi-image in-context editing | https://github.com/VectorSpaceLab/OmniGen2 |

Decision (sponsor, 2026-11-14): ID-7 compares **Qwen-Image-Edit-2511** with the current FLUX.2 klein route instead of DreamO: Apache-2.0, not gated, and aimed at multi-person identity. 20B does not fit the RTX 2070's 8 GB, so it runs quantized with CPU offload; its speed is measured in the bake-off.

## 3. Replacements to look at if a commercial release needs them (inference, not measured)
- Face-identity judge: a face-recognition model with a commercial licence, re-qualified on continuity corpus 2 with the same rule and bar (ADR-0151); or the qualified cloud continuity judge (ADR-0134) as the ranking signal once one passes.
- Ambience: ACE-Step (MIT) prompted for ambient textures, or a CC0 field-recording library; or Stable Audio Open (gated, its own community licence; not read here).

## 4. Unknowns
- The licence on the VieNeu v3 Turbo weights themselves (the model card was not read).
- OmniGen2's weights licence; DreamO's exact base model.
- Whether InsightFace's commercial terms for `buffalo_l` are affordable (requires contacting them).
