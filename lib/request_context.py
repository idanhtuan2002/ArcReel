"""Entry-request and executing-task identity for H7 correlation.

An entry request is one HTTP request or one embedded Agent tool call. The entry
binds a ``request_id`` for its duration; ``GenerationQueue.enqueue_task`` reads
it and persists it on the task row. Work that runs with no bound entry (worker
internals, CLI scripts) enqueues with ``request_id`` NULL rather than a
fabricated identity.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

_REQUEST_ID: ContextVar[str | None] = ContextVar("arcreel_request_id", default=None)
_TASK_ID: ContextVar[str | None] = ContextVar("arcreel_task_id", default=None)

# Caller-supplied ``X-Request-ID`` values are reused only in opaque identifier
# shapes (a UUID, 32 hex digits as in a W3C trace ID, or an ID this module
# minted), so no free text, name or credential-shaped value is persisted or exported.
_ACCEPTED_REQUEST_ID = re.compile(
    r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|(?:req_)?[0-9a-f]{32})"
)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def accept_or_mint_request_id(candidate: str | None) -> str:
    """Reuse a well-formed caller-supplied ID, otherwise mint a fresh one."""
    if candidate is not None and _ACCEPTED_REQUEST_ID.fullmatch(candidate):
        return candidate
    return new_request_id()


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


@contextmanager
def bound_request_id(request_id: str) -> Generator[str]:
    """Bind ``request_id`` as the current entry request for the ``with`` body."""
    token = _REQUEST_ID.set(request_id)
    try:
        yield request_id
    finally:
        _REQUEST_ID.reset(token)


def current_task_id() -> str | None:
    return _TASK_ID.get()


@contextmanager
def bound_task(task_id: str, *, request_id: str | None) -> Generator[None]:
    """Bind the queue task being executed, and the entry request that created it.

    Usage rows and version records written while the task runs carry this
    ``task_id``; follow-up tasks it enqueues inherit its ``request_id``.
    """
    task_token = _TASK_ID.set(task_id)
    request_token = _REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _REQUEST_ID.reset(request_token)
        _TASK_ID.reset(task_token)


def task_attribution() -> dict[str, str]:
    """``{"task_id": ...}`` while a queue task is executing, otherwise empty."""
    task_id = _TASK_ID.get()
    return {} if task_id is None else {"task_id": task_id}


__all__ = [
    "accept_or_mint_request_id",
    "bound_request_id",
    "bound_task",
    "current_request_id",
    "current_task_id",
    "new_request_id",
    "task_attribution",
]
