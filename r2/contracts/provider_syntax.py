"""Provider-syntax denylist for provider-neutral semantic strings.

Stable semantic contracts (identity constraints, PromptPlan intent) express
*what* execution must achieve. Provider payload keys, CLI flags and engine brand
names must never appear in those values; the translation to provider syntax
happens only at the PromptCompiler. This module rejects the syntax at the value
level, complementing the field-name checks in the architecture fitness tests.
"""

from __future__ import annotations

import re

# Structural patterns — format, not brand. High signal, brand-independent.
_STRUCTURAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"--[a-zA-Z][\w-]*"),  # CLI flag: --cref, --cw, --ar, --stylize
    re.compile(r"::\s*-?\d*\.?\d*"),  # Midjourney multi-prompt weight separator
    re.compile(r"<\s*(?:lora|hypernet(?:work)?|embedding|ti|ip-?adapter|controlnet)\b", re.IGNORECASE),
    re.compile(r"\([^()\r\n]{1,80}:\s*-?\d+(?:\.\d+)?\s*\)"),  # A1111 weight: (red hair:1.3)
)

# Brand / payload-key tokens that are not ordinary appearance/style vocabulary.
_TOKEN_DENYLIST: tuple[str, ...] = (
    "midjourney",
    "niji",
    "dall-e",
    "dalle",
    "stable diffusion",
    "stable-diffusion",
    "stablediffusion",
    "sdxl",
    "automatic1111",
    "a1111",
    "comfyui",
    "civitai",
    "safetensors",
    "controlnet",
    "ip-adapter",
    "ipadapter",
    "cfg_scale",
    "cfg scale",
    "denoising_strength",
    "guidance_scale",
    "num_inference_steps",
    "negative_prompt",
)

_TOKEN_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(tok) for tok in _TOKEN_DENYLIST) + r")(?!\w)",
    re.IGNORECASE,
)


def detect_provider_syntax(value: str) -> tuple[str, ...]:
    """Return the distinct provider-syntax fragments found in ``value`` (empty
    tuple when the string is provider-neutral)."""
    hits: list[str] = []
    for pattern in _STRUCTURAL_PATTERNS:
        hits += (m.group(0).strip() for m in pattern.finditer(value))
    hits += (m.group(0) for m in _TOKEN_PATTERN.finditer(value))
    seen: dict[str, None] = {}
    for hit in hits:
        key = hit.lower()
        if hit and key not in seen:
            seen[key] = None
    return tuple(seen)


def reject_provider_syntax(value: str, *, field: str) -> str:
    """Validator helper: return the stripped value, or raise ``ValueError`` when
    it carries provider syntax."""
    hits = detect_provider_syntax(value)
    if hits:
        raise ValueError(f"{field} carries provider syntax (denied): {', '.join(hits)}")
    return value.strip()
