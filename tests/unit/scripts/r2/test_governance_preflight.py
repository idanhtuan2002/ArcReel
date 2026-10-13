"""The operator command exposes explicit paths and sanitized failures."""

from pathlib import Path

from scripts.r2.governance_preflight import build_parser, main


def test_operator_parser_accepts_environment_name_instead_of_credentials() -> None:
    args = build_parser().parse_args(
        [
            "serve",
            "--root",
            "/operator/governance",
            "--socket-directory",
            "/run/operator",
            "--database-url-env",
            "GOVERNANCE_DSN",
        ]
    )
    assert args.root == Path("/operator/governance")
    assert args.socket_directory == Path("/run/operator")
    assert args.database_url_env == "GOVERNANCE_DSN"


def test_operator_failure_does_not_echo_path_or_environment_secret(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["governance_preflight", "preflight", "--root", "/host-path-canary"])
    monkeypatch.setenv("DATABASE_URL", "invalid-dsn-secret-canary")
    assert main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Governance operator command failed\n"
