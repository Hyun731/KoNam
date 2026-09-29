"""문서 분석(업로드 문서 기반 상담) 테이블

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE analyses (
            id          UUID PRIMARY KEY,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            lang        TEXT NOT NULL,
            filename    TEXT NOT NULL,
            mime        TEXT,
            file_size   INTEGER,
            page_count  INTEGER,
            text        TEXT NOT NULL,
            status      TEXT NOT NULL,
            stage       TEXT,
            intake      JSONB,
            answers     JSONB,
            result      JSONB,
            error       TEXT
        )
        """
    )
    op.execute("CREATE INDEX ix_analyses_created_at ON analyses (created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analyses")
