"""assemble_backend — 「provider config + model → backend」统一构造入口。

按 is_custom_provider 单分支分流到内置 / 自定义两族（一道门、门后两个对称房间，见 ADR 0039）。
构造拆两段：async 装载（查 DB/config，产出 LoadedConfig 信封）/ sync 纯闭包构造。缝无状态、纯构造，
backend 实例缓存留在调用方编排层、不进缝。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lib.backend_assembly.loaded_config import LoadedConfig
from lib.backend_assembly.specs import get_provider_spec
from lib.config.registry import PROVIDER_REGISTRY
from lib.custom_provider import is_custom_provider
from r2.host_hardening.paid_routes import current_release_mode, media_route, require_paid_route, route_binding
from r2.host_hardening.provider_capabilities import ReleaseMode

if TYPE_CHECKING:
    from lib.config.resolver import ConfigResolver


async def _load_builtin_config(resolver: ConfigResolver, provider_id: str, rate_limiter: Any | None) -> LoadedConfig:
    """内置侧 async 装载段：查 DB/config 产出 LoadedConfig 信封。

    凭证 overlay 来自 db_config（resolver.provider_config）；registry meta 提供 default_base_url /
    api_model_name 来源；rate_limiter 由调用方注入（共享实例）。这一段是唯一的 await/DB 触点，
    之后 sync 构造闭包只读信封。
    """
    db_config = await resolver.provider_config(provider_id)
    return LoadedConfig(
        credentials=dict(db_config),
        provider_meta=PROVIDER_REGISTRY.get(provider_id),
        rate_limiter=rate_limiter,
    )


#: Built-in provider config keys that tune throughput, not where or as whom a request goes.
#: Changing them must not invalidate a route qualification.
_TUNING_KEY_RE = re.compile(r"(_rpm|_max_workers|request_gap)$")


async def paid_route_binding(
    *, provider_id: str, media_type: str, resolver: ConfigResolver, model_id: str | None = None
) -> str:
    """The provider configuration a route qualification is bound to.

    - Built-in providers bind their stored provider config minus throughput tuning keys: base URL,
      credentials and any other request-shaping setting.
    - Custom providers bind the provider row's base URL, key and discovery format, plus, for
      ``model_id``, the model's endpoint and the endpoint definition when it is a user-defined one.

    Only :func:`route_binding`'s digest leaves this function.
    """
    if is_custom_provider(provider_id):
        from lib.custom_provider import is_custom_endpoint, parse_endpoint_key, parse_provider_id
        from lib.db.repositories.custom_endpoint_repo import CustomEndpointRepository
        from lib.db.repositories.custom_provider_repo import CustomProviderRepository

        fields: dict[str, object] = {}
        async with resolver._open_session() as (session, _):
            db_id = parse_provider_id(provider_id)
            repo = CustomProviderRepository(session)
            provider = await repo.get_provider(db_id)
            if provider is not None:
                fields.update(
                    base_url=provider.base_url, api_key=provider.api_key, discovery_format=provider.discovery_format
                )
            model = await repo.get_model_by_ids(db_id, model_id) if model_id else None
            if model is not None:
                fields["endpoint"] = model.endpoint
                if is_custom_endpoint(model.endpoint):
                    row = await CustomEndpointRepository(session).get(parse_endpoint_key(model.endpoint))
                    fields["endpoint_definition"] = row.definition if row is not None else None
        return route_binding(provider_id=provider_id, media_type=media_type, **fields)
    config = await resolver.provider_config(provider_id)
    request_shaping = {key: value for key, value in dict(config).items() if not _TUNING_KEY_RE.search(key)}
    return route_binding(provider_id=provider_id, media_type=media_type, **request_shaping)


async def require_built_backend_qualified(
    backend: Any, *, provider_id: str, media_type: str, model_id: str | None, resolver: ConfigResolver
) -> None:
    """Release gate on the backend actually built: its real model and the configuration bound to it.

    A custom provider falls back to its default model when the requested one is missing or disabled,
    so the gate checks ``backend.model``, not the requested id; a qualification of one model never
    opens another. DEV does nothing.
    """
    if current_release_mode() is ReleaseMode.DEV:
        return
    actual_model = getattr(backend, "model", None) or model_id
    binding = await paid_route_binding(
        provider_id=provider_id, media_type=media_type, resolver=resolver, model_id=actual_model
    )
    require_paid_route(media_route(provider_id, media_type), model_id=actual_model, binding=binding)


async def assemble_backend(
    *,
    provider_id: str,
    media_type: str,
    model_id: str | None,
    resolver: ConfigResolver,
    rate_limiter: Any | None = None,
) -> Any:
    """统一构造入口。按 provider_id 是否自定义分流；未登记的内置 provider × media fail-loud。

    发布部署（``ARCREEL_RELEASE_MODE=PRODUCTION_CANDIDATE``）下，构造出的 backend 在交给调用方
    之前按其实际模型与当下供应商配置过路线闸门（ADR-0091）；构造本身不发任何供应商请求，
    没有当前资质即拒绝，一个请求都不会发出。DEV 不读取、不计算绑定。
    """
    if is_custom_provider(provider_id):
        from lib.custom_provider.loader import load_custom_backend

        # 借 resolver 的 session（bound 时复用其事务上下文）：自定义装载与简单族装载共用同一
        # session_factory，调用方在 resolver.session() 内构造时复用同一连接，避免另开 factory。
        async with resolver._open_session() as (session, _):
            backend = await load_custom_backend(
                session=session, provider_id=provider_id, model_id=model_id, media_type=media_type
            )
    else:
        spec = get_provider_spec(provider_id, media_type)  # 未登记 → ValueError（fail-loud）
        config = await _load_builtin_config(resolver, provider_id, rate_limiter)
        backend = spec.build_backend(config, model_id)
    await require_built_backend_qualified(
        backend, provider_id=provider_id, media_type=media_type, model_id=model_id, resolver=resolver
    )
    return backend
