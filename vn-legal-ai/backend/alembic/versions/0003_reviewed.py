"""법령 코퍼스 검토 기록 (#14): 사람이 원문·메타데이터를 확인했는지 남긴다.

Revision ID: 0003
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 수동으로 먼저 적용한 DB에서도 다시 돌 수 있도록 IF NOT EXISTS
    op.execute(
        """
        ALTER TABLE legal_documents
            ADD COLUMN IF NOT EXISTS reviewed    BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS reviewed_by TEXT,
            ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS review_note TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal_documents
            DROP COLUMN IF EXISTS review_note,
            DROP COLUMN IF EXISTS reviewed_at,
            DROP COLUMN IF EXISTS reviewed_by,
            DROP COLUMN IF EXISTS reviewed
        """
    )
