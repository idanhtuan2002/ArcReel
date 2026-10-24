"""Release-mode gate over every paid outbound route class (ADR-0091).

A deployment runs in ``DEV`` (default) or ``PRODUCTION_CANDIDATE`` release mode,
set by ``ARCREEL_RELEASE_MODE``. ``DEV`` keeps every route usable. In
``PRODUCTION_CANDIDATE`` a paid route is refused before any provider request
unless the route has a current qualification. Route classes:

- ``media``: a built-in provider x media type pair from the backend spec registry;
- ``custom_media``: a custom-provider media type (declarative image/video/text/audio);
- ``agent``: the embedded Agent's model provider;
- ``trial_run``: a custom-provider endpoint trial run.

The qualification lookup is pluggable so runtime route qualifications can be
consulted without this module owning their storage.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from r2.host_hardening.provider_capabilities import ReleaseMode

RELEASE_MODE_ENV = "ARCREEL_RELEASE_MODE"

PaidRouteKind = Literal["media", "custom_media", "agent", "trial_run", "story"]

#: Media types a custom provider can serve through the declarative runtime.
CUSTOM_MEDIA_TYPES: frozenset[str] = frozenset({"image", "video", "text", "audio"})


class ReleaseModeConfigError(ValueError):
    """``ARCREEL_RELEASE_MODE`` holds a value that is not a release mode."""


def current_release_mode() -> ReleaseMode:
    """The deployment's release mode; unset means ``DEV``. An unknown value is a configuration error."""
    raw = (os.environ.get(RELEASE_MODE_ENV) or "").strip()
    if not raw:
        return ReleaseMode.DEV
    try:
        return ReleaseMode(raw.upper())
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in ReleaseMode)
        raise ReleaseModeConfigError(f"{RELEASE_MODE_ENV}={raw!r} is not one of: {allowed}") from exc


@dataclass(frozen=True, order=True)
class PaidRoute:
    kind: PaidRouteKind
    provider_id: str | None = None
    media_type: str | None = None

    @property
    def ref(self) -> str:
        return ":".join(part for part in (self.kind, self.provider_id, self.media_type) if part)


class PaidRouteUnqualifiedError(RuntimeError):
    """A paid route was refused in a release deployment because it has no current qualification.

    Carries a stable ``code`` and ``params`` like the backend capability errors, so the
    worker persists it as a structured task failure and the read side renders it.
    """

    code = "paid_route_unqualified"

    def __init__(self, route: PaidRoute, model_id: str | None) -> None:
        self.route = route
        self.model_id = model_id
        self.params: dict[str, str] = {"route": route.ref, "model": model_id or ""}
        super().__init__(f"{self.code}: {route.ref} model={model_id or '-'}")


#: ``(route, model_id, binding) -> bool``: whether the route currently holds a qualification for
#: this exact model and provider configuration (``binding``, see :func:`route_binding`).
QualificationLookup = Callable[[PaidRoute, "str | None", "str | None"], bool]


def _no_qualifications(_route: PaidRoute, _model_id: str | None, _binding: str | None) -> bool:
    return False


_qualification_lookup: QualificationLookup = _no_qualifications


def set_qualification_lookup(lookup: QualificationLookup | None) -> None:
    """Install the qualification lookup; ``None`` restores "nothing is qualified"."""
    global _qualification_lookup
    _qualification_lookup = lookup or _no_qualifications


_canary: ContextVar[tuple[PaidRoute, str | None] | None] = ContextVar("paid_route_canary", default=None)


@contextmanager
def qualification_canary(route: PaidRoute, model_id: str | None) -> Generator[None]:
    """Let exactly this route and model through the gate while its qualification canary runs.

    The canary is the one paid call an unqualified route may make, started by the operator.
    """
    token = _canary.set((route, model_id))
    try:
        yield
    finally:
        _canary.reset(token)


def route_binding(**fields: object) -> str:
    """Digest of the provider configuration a route is qualified for (base URL, credentials, account).

    Only the digest is stored, never a credential. A changed key, base URL or account yields a
    different binding, so a qualification does not carry over to another configuration or to a
    deployment restored from backup with other credentials.
    """
    payload = json.dumps({key: fields[key] for key in sorted(fields)}, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(b"arcreel-route-binding\0" + payload.encode("utf-8")).hexdigest()


def require_paid_route(
    route: PaidRoute,
    *,
    model_id: str | None,
    binding: str | None = None,
    release_mode: ReleaseMode | None = None,
) -> None:
    """Refuse ``route`` in a release deployment unless it is currently qualified for ``binding``."""
    mode = release_mode if release_mode is not None else current_release_mode()
    if mode is ReleaseMode.DEV:
        return
    if _canary.get() == (route, model_id):
        return
    if not _qualification_lookup(route, model_id, binding):
        raise PaidRouteUnqualifiedError(route, model_id)


def media_route(provider_id: str, media_type: str) -> PaidRoute:
    """The route class that ``assemble_backend`` builds for ``provider_id`` x ``media_type``."""
    # Duplicates lib.custom_provider's "custom-" prefix instead of importing it, matching
    # route_inventory: lib.backend_assembly reaches this module.
    if provider_id.startswith("custom-"):
        return PaidRoute("custom_media", provider_id=provider_id, media_type=media_type)
    return PaidRoute("media", provider_id=provider_id, media_type=media_type)


def paid_route_inventory() -> frozenset[PaidRoute]:
    """Every paid route class, derived from the backend spec registry plus the fixed classes."""
    from lib.backend_assembly.specs import PROVIDER_SPEC_REGISTRY

    routes = {PaidRoute("media", provider_id=p, media_type=m) for p, m in PROVIDER_SPEC_REGISTRY}
    routes |= {PaidRoute("custom_media", media_type=m) for m in CUSTOM_MEDIA_TYPES}
    routes |= {PaidRoute("agent"), PaidRoute("trial_run"), PaidRoute("story", provider_id="gemini-aistudio")}
    return frozenset(routes)


__all__ = [
    "CUSTOM_MEDIA_TYPES",
    "RELEASE_MODE_ENV",
    "PaidRoute",
    "PaidRouteKind",
    "PaidRouteUnqualifiedError",
    "QualificationLookup",
    "ReleaseModeConfigError",
    "current_release_mode",
    "media_route",
    "paid_route_inventory",
    "qualification_canary",
    "require_paid_route",
    "route_binding",
    "set_qualification_lookup",
]
