"""Scoped append-only child delegations and owner decision provenance."""

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


def _ceiling(column: str) -> tuple[CheckConstraint, CheckConstraint]:
    return (
        CheckConstraint(f"octet_length({column}) <= 1048576", name=f"ck_auto_grant_{column}_pg").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint(f"length(CAST({column} AS BLOB)) <= 1048576", name=f"ck_auto_grant_{column}_sqlite").ddl_if(
            dialect="sqlite"
        ),
    )


class AutomationGrantEventModel(Base):
    __tablename__ = "auto_grant_events"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    grant_json: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id"],
            ["auto_production_runs.user_id", "auto_production_runs.project_name", "auto_production_runs.run_id"],
            name="fk_auto_grant_run",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("user_id", "project_name", "run_id", "grant_id", "version", name="uq_auto_grant_event_scope"),
        CheckConstraint("version >= 1", name="ck_auto_grant_version"),
        *_ceiling("grant_json"),
    )


class AutomationGrantHeadModel(Base):
    __tablename__ = "auto_grant_heads"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "grant_id", "version"],
            [
                "auto_grant_events.user_id",
                "auto_grant_events.project_name",
                "auto_grant_events.run_id",
                "auto_grant_events.grant_id",
                "auto_grant_events.version",
            ],
            name="fk_auto_grant_head_event",
            ondelete="RESTRICT",
        ),
    )


class AutomationDecisionModel(Base):
    __tablename__ = "auto_authorization_decisions"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    grant_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authorization_json: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "grant_id", "grant_version"],
            [
                "auto_grant_events.user_id",
                "auto_grant_events.project_name",
                "auto_grant_events.run_id",
                "auto_grant_events.grant_id",
                "auto_grant_events.version",
            ],
            name="fk_auto_decision_grant",
            ondelete="RESTRICT",
        ),
        *_ceiling("authorization_json"),
    )
