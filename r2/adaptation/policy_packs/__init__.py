"""Immutable M6 domain policy-pack manifests (plan Task 8).

Each ``*.json`` sibling is a named source identity plus stable rule metadata for one
M6 v1 profile, loaded only through ``r2.adaptation.profiles.ProfilePackRegistry`` —
never read directly, never hot-reloaded. Distinct from ``agent_runtime_profile/`` at
the repository root, which configures the embedded creative Agent runtime: an
unrelated concern with no policy-pack shape of its own.
"""

from __future__ import annotations
