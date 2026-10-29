#!/bin/bash
# B1 C3 witness: a predecessor FORMAT revision chain and its referencing head row survive the M10 PACKAGING-kind
# migration (5d2a7c3e8b11) up, an allowed downgrade (no PACKAGING rows) and a re-upgrade; a PACKAGING row makes the
# downgrade refuse. Run from the repository root against the disposable PG16 container m10b-test-pg.
set -uo pipefail
DB=m10_b1_c3_witness
PSQL="docker exec m10b-test-pg psql -U postgres -v ON_ERROR_STOP=1 -X -q"
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55491/$DB
echo "== source $(git rev-parse HEAD) migration sha256 $(sha256sum alembic/versions/5d2a7c3e8b11_*.py | cut -d' ' -f1)"
$PSQL -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" -c "CREATE DATABASE $DB"
uv run alembic upgrade 4c1f0e2a9b10 2>&1 | tail -1; uv run alembic current 2>&1 | tail -1
$PSQL -d $DB -c "INSERT INTO users (id, username, role, is_active, created_at, updated_at) VALUES ('default','default','user',true,now(),now()) ON CONFLICT DO NOTHING" \
 -c "INSERT INTO m8_candidate_heads (user_id, project_name, candidate_id, current_revision, head_version, created_at, updated_at) VALUES ('default','project','fmt-1',2,2,now(),now())" \
 -c "INSERT INTO m8_candidate_revisions (user_id, project_name, candidate_id, revision, parent_revision, kind, payload_json, payload_digest, lineage_json, created_by, created_at) VALUES ('default','project','fmt-1',1,NULL,'FORMAT','{}','sha256:$(printf 'a%.0s' {1..64})','{}','default',now()), ('default','project','fmt-1',2,1,'FORMAT','{}','sha256:$(printf 'b%.0s' {1..64})','{}','default',now())"
rows() { $PSQL -d $DB -tA -c "SELECT r.candidate_id, r.revision, r.parent_revision, r.kind, r.payload_digest, h.current_revision FROM m8_candidate_revisions r JOIN m8_candidate_heads h USING (user_id, project_name, candidate_id) ORDER BY r.revision" -c "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_m8_candidate_revisions_kind'"; }
echo "== at 4c1f0e2a9b10"; rows
echo "== upgrade head"; uv run alembic upgrade head 2>&1 | tail -1; uv run alembic current 2>&1 | tail -1; rows
echo "== allowed downgrade (no PACKAGING rows)"; uv run alembic downgrade 4c1f0e2a9b10 2>&1 | tail -1; uv run alembic current 2>&1 | tail -1; rows
echo "== re-upgrade"; uv run alembic upgrade head 2>&1 | tail -1; uv run alembic current 2>&1 | tail -1; rows
echo "== PACKAGING row present: downgrade must refuse"
$PSQL -d $DB -c "INSERT INTO m8_candidate_heads (user_id, project_name, candidate_id, current_revision, head_version, created_at, updated_at) VALUES ('default','project','pkg-1',1,1,now(),now())" \
 -c "INSERT INTO m8_candidate_revisions (user_id, project_name, candidate_id, revision, parent_revision, kind, payload_json, payload_digest, lineage_json, created_by, created_at) VALUES ('default','project','pkg-1',1,NULL,'PACKAGING','{}','sha256:$(printf 'c%.0s' {1..64})','{}','default',now())"
uv run alembic downgrade 4c1f0e2a9b10 > /tmp/claude-1000/b1c3-down.log 2>&1; echo "downgrade exit=$?"; grep -o "M10_[A-Z_]*" /tmp/claude-1000/b1c3-down.log | head -1
uv run alembic current 2>&1 | tail -1
$PSQL -d $DB -tA -c "SELECT kind, count(*) FROM m8_candidate_revisions GROUP BY kind ORDER BY kind"
