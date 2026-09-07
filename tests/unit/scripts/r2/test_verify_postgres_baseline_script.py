from r2.bootstrap import r2_root

SCRIPT_PATH = r2_root() / "scripts" / "r2" / "verify_postgres_baseline.sh"


def _script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_is_fail_fast_and_localhost_only():
    text = _script()
    assert "set -Eeuo pipefail" in text
    assert "127.0.0.1:${R2_PG_PORT}:5432" in text
    assert "--host 127.0.0.1" in text


def test_script_uses_isolated_resources_and_cleanup_trap():
    text = _script()
    assert 'PG_CONTAINER="${R2_PG_CONTAINER:-r2-m0-postgres}"' in text
    assert "com.content-production-os.r2-m0=1" in text
    assert "trap cleanup EXIT" in text


def test_script_uses_postgresql_and_arcreel_server_entrypoint():
    text = _script()
    assert "postgresql+asyncpg://" in text
    assert "uv run alembic upgrade head" in text
    assert "uv run uvicorn server.app:app" in text


def test_script_performs_real_backend_restart():
    text = _script()
    assert text.count("start_backend") >= 3
    assert "stop_backend" in text
    assert "backend restart health: PASS" in text
