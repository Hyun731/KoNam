"""채팅 미해결 질문(open_questions)과 API 사용량 기록(usage_log) 테이블

Revision ID: 0005
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# asyncpg는 한 번에 여러 문장을 실행하지 못하므로 문장별로 나눠 둔다. 이미 적용된 DB에서도 안전하게 IF NOT EXISTS
UPGRADE = [
    """
    CREATE TABLE IF NOT EXISTS open_questions (
        id           BIGSERIAL PRIMARY KEY,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        session_id   TEXT,
        analysis_id  UUID,
        source       TEXT NOT NULL CHECK (source IN ('chat', 'analysis')),
        question     TEXT NOT NULL,
        resolved     BOOLEAN NOT NULL DEFAULT false,
        resolved_at  TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_open_questions_session ON open_questions (session_id, resolved)",
    "CREATE INDEX IF NOT EXISTS ix_open_questions_analysis ON open_questions (analysis_id, resolved)",
    """
    CREATE TABLE IF NOT EXISTS usage_log (
        id               BIGSERIAL PRIMARY KEY,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        kind             TEXT NOT NULL CHECK (kind IN ('chat', 'analysis')),
        ref              TEXT,
        model_breakdown  JSONB NOT NULL DEFAULT '{}'::jsonb,
        input_tokens     INTEGER NOT NULL DEFAULT 0,
        output_tokens    INTEGER NOT NULL DEFAULT 0,
        cost_usd         NUMERIC(12, 6) NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_usage_log_created_at ON usage_log (created_at DESC)",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_log")
    op.execute("DROP TABLE IF EXISTS open_questions")
