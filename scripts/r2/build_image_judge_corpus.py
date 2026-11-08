"""Build the storyboard-pair corpus that qualifies the ranking image judge (ADR-0112).

From a stories directory (``{"title", "scenes": [{"narration", "image_prompt"}]}`` per file, as in the reviewer
corpus), the first ``--per-story`` scenes of each story get one storyboard from the local FLUX.2 klein workflow (the
production image route's model at 576x1024, 4 steps, seed fixed per scene). Each scene then forms a pair: its own
storyboard against the storyboard of another scene of the same story, with its narration line. ``pairs.json`` lists
the pairs with each image's sha256 and the corpus digest; existing images are reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def _workflow(prompt: str, seed: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-4b-Q4_K_M.gguf"}},
        "2": {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "Qwen3-4B-Q4_K_M.gguf", "type": "flux2"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": 1.0},
        },
        "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "8": {"class_type": "Flux2Scheduler", "inputs": {"steps": 4, "width": 576, "height": 1024}},
        "9": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 576, "height": 1024, "batch_size": 1}},
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["10", 0],
                "guider": ["6", 0],
                "sampler": ["7", 0],
                "sigmas": ["8", 0],
                "latent_image": ["9", 0],
            },
        },
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": prefix}},
    }


def _generate(base: str, prompt: str, seed: int, out: Path) -> None:
    body = json.dumps({"prompt": _workflow(prompt, seed, "judge-corpus/" + uuid.uuid4().hex), "client_id": "judge"})
    request = urllib.request.Request(base + "/prompt", body.encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        prompt_id = json.load(response)["prompt_id"]
    while True:
        with urllib.request.urlopen(f"{base}/history/{prompt_id}") as response:
            history = json.load(response)
        if prompt_id in history:
            entry = history[prompt_id]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(entry["status"])[:800])
            image = entry["outputs"]["13"]["images"][0]
            query = urllib.parse.urlencode({k: image[k] for k in ("filename", "subfolder", "type")})
            with urllib.request.urlopen(f"{base}/view?{query}") as response:
                out.write_bytes(response.read())
            return
        time.sleep(1)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stories", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--comfyui", default="http://127.0.0.1:8188")
    parser.add_argument("--per-story", type=int, default=2)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pairs = []
    for story_file in sorted(args.stories.glob("*.json")):
        scenes = json.loads(story_file.read_text(encoding="utf-8"))["scenes"][: args.per_story]
        images = []
        for index, scene in enumerate(scenes):
            image = args.out / f"{story_file.stem}_s{index}.png"
            if not image.is_file():
                seed = int(hashlib.sha256(f"{story_file.stem}:{index}".encode()).hexdigest()[:8], 16)
                _generate(args.comfyui, scene["image_prompt"], seed, image)
            images.append(image)
        for index, scene in enumerate(scenes):
            other = images[(index + 1) % len(images)]
            if other == images[index]:
                continue
            pairs.append(
                {
                    "pair_id": f"{story_file.stem}_s{index}",
                    "line": scene["narration"],
                    "own": images[index].name,
                    "own_sha256": _sha256(images[index]),
                    "other": other.name,
                    "other_sha256": _sha256(other),
                }
            )
    digest = "sha256:" + hashlib.sha256(json.dumps(pairs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    manifest = {"schema": "r2.image-judge-corpus.v1", "corpus_digest": digest, "pairs": pairs}
    (args.out / "pairs.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pairs": len(pairs), "corpus_digest": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
