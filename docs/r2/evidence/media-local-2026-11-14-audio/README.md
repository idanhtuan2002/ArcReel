# Local audio services for the film finish (music bed, ambience), 2026-11-14

Both run on the data disk `/mnt/arcreel/D/ArcReel` (the system disk is 93 % full and the launch profile needs 8 GB free there).

| Service | Code | Launch | Port | VRAM generating / idle | Speed (RTX 2070) |
|---|---|---|---|---|---|
| Music bed (ADR-0143) | ACE-Step 1.5 `ca1e85f`, upstream `acestep-api` as is; 2B turbo DiT, LM off, CPU offload incl. DiT | `ace-step-api.sh` | 8001 | 5.4 GB / 0.4 GB | 50 s of music in ~4 s after a ~15 s first load |
| Ambience (ADR-0150) | MMAudio `974010a` (`large_44k_v2`, float16), shim `mmaudio_ambience_server.py.txt` (copy of `/mnt/arcreel/D/ArcReel/mmaudio_ambience_server.py`) | `mmaudio-ambience.sh` | 8002 | 6.4 GB / 0.15 GB | 8 s clip in ~7 s after a ~60 s first load |

Install notes:
- ACE-Step: `uv sync` in the clone (venv 7.6 GB); checkpoints (~10 GB) under `ace-step/checkpoints` (`ACESTEP_CHECKPOINTS_DIR`). The unified-repo download stalled once on the LM file; a resumed `snapshot_download` finished it.
- MMAudio: torch must be pinned to a matching stack (`torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0` from the cu124 index, `torchcodec<0.3`); its `pip install -e .` otherwise pulls a torch that cannot load `libtorchaudio`. Weights 3.9 GB + 2.1 GB, plus `apple/DFN5B-CLIP-ViT-H-14-384`; the Hub download of `open_clip_pytorch_model.bin` stalled twice and was fetched with `curl -C -` into the HF cache.
- App env (start script, Human): `ARCREEL_MUSIC_URL=http://127.0.0.1:8001`, `ARCREEL_MUSIC_FREE_URLS=http://127.0.0.1:8188/free`, `ARCREEL_AMBIENCE_URL=http://127.0.0.1:8002`.

Real check: a three-unit sample (still clips with camera moves, `cinematic_warm` grade, VieNeu narration, the ACE-Step bed, rain and market ambience) rendered to 18.02 s, −14.16 LUFS integrated, −0.96 dBTP; music 16 dB under, ambience ~22 dB under the narration.
