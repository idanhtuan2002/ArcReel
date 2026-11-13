"""TextGenerator — 文本生成 + 记账包装层。

类似 MediaGenerator，组合 TextBackend + Ledger，
调用方无需关心记账细节。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lib.db.base import DEFAULT_USER_ID
from lib.ledger import Ledger
from lib.providers import require_provider_pair
from lib.telemetry import clears_baggage_at_provider_boundary
from lib.text_backends.base import (
    TEXT_TASK_TIERS,
    TextGenerationRequest,
    TextGenerationResult,
    TextTaskTier,
    TextTaskType,
)
from lib.text_backends.factory import (
    create_text_backend_for_model,
    create_text_backend_for_task,
    project_text_fallbacks,
)
from lib.text_backends.fallback_rules import RUN_FALLBACK_RULES
from lib.text_backends.route_failure import is_route_failure

if TYPE_CHECKING:
    from lib.text_backends.base import TextBackend

logger = logging.getLogger(__name__)


class TextGenerator:
    """组合 TextBackend + Ledger，统一封装文本生成 + 记账。"""

    def __init__(
        self,
        backend: TextBackend,
        ledger: Ledger,
        provider_id: str,
        *,
        task_type: TextTaskType | None = None,
        fallbacks: tuple[tuple[str, str], ...] = (),
    ):
        require_provider_pair("text", backend, provider_id)
        self.backend = backend
        self.ledger = ledger
        self._provider_id = provider_id
        self._task_type = task_type
        #: Models (provider, model) this generator moves to, in order, when its model fails on its route (ADR-0139).
        self._fallbacks = list(fallbacks) if task_type is not None else []

    @property
    def model(self) -> str:
        """当前 backend 的模型名称。"""
        return self.backend.model

    @classmethod
    async def create(
        cls,
        task_type: TextTaskType,
        project_name: str | None = None,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> TextGenerator:
        """工厂方法：根据任务类型创建对应的 backend + ledger。"""
        if (provider_id is None) != (model_id is None):
            raise ValueError("provider_id and model_id must be supplied together")
        if provider_id is not None:
            assert model_id is not None
            backend, resolved_provider = await create_text_backend_for_model(
                task_type, provider_id=provider_id, model_id=model_id
            )
            return cls(backend, Ledger(), resolved_provider)
        rules = RUN_FALLBACK_RULES.get()
        pinned = rules.text_route if rules is not None else None
        if pinned is not None and TEXT_TASK_TIERS[task_type] is TextTaskTier.COMPLEX:
            # An open run's script work stays on the model its policy froze (ADR-0139).
            backend, resolved_provider = await create_text_backend_for_model(
                task_type, provider_id=pinned[0], model_id=pinned[1]
            )
        else:
            backend, resolved_provider = await create_text_backend_for_task(task_type, project_name)
        fallbacks = tuple(
            pair for pair in project_text_fallbacks(project_name) if pair != (resolved_provider, backend.model)
        )
        return cls(backend, Ledger(), resolved_provider, task_type=task_type, fallbacks=fallbacks)

    async def _fall_back(self, error: BaseException) -> bool:
        """Move to the next fallback model that can do this task; ``False`` when none is left."""
        assert self._task_type is not None
        while self._fallbacks:
            provider_id, model_id = self._fallbacks.pop(0)
            try:
                backend, resolved = await create_text_backend_for_model(
                    self._task_type, provider_id=provider_id, model_id=model_id
                )
            except Exception as unusable:
                logger.warning("text fallback %s/%s unusable: %s", provider_id, model_id, type(unusable).__name__)
                continue
            logger.warning(
                "text model %s/%s failed on its route (%s); moving to %s/%s",
                self._provider_id,
                self.backend.model,
                type(error).__name__,
                resolved,
                backend.model,
            )
            self.backend, self._provider_id = backend, resolved
            return True
        return False

    @clears_baggage_at_provider_boundary
    async def generate(
        self,
        request: TextGenerationRequest,
        project_name: str | None = None,
        *,
        user_id: str = DEFAULT_USER_ID,
        execution_id: str | None = None,
    ) -> TextGenerationResult:
        """生成文本并自动记录用量；给出 ``execution_id`` 时，成功后把这条用量绑定到该用户的 M7 执行。

        A call that fails on its route (quota, key, missing model, provider down) is made again on the next fallback
        model of the project's settings, if any (ADR-0139); the generator stays on that model afterwards."""
        while True:
            try:
                return await self._generate_once(request, project_name, user_id=user_id, execution_id=execution_id)
            except Exception as error:
                if not self._fallbacks or not is_route_failure(error) or not await self._fall_back(error):
                    raise

    async def _generate_once(
        self,
        request: TextGenerationRequest,
        project_name: str | None,
        *,
        user_id: str,
        execution_id: str | None,
    ) -> TextGenerationResult:
        async with self.ledger.record(
            project_name=project_name or "",
            call_type="text",
            model=self.backend.model,
            prompt=request.prompt[:500],
            provider=self._provider_id,
            user_id=user_id,
        ) as call:
            result = await self.backend.generate(request)
            call.success(result)
        if execution_id is not None:
            await self.ledger.bind_execution(call_id=call.call_id, execution_id=execution_id)
        return result
