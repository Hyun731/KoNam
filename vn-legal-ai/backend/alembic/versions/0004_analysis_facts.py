"""문서 분석: 문서 사실(주장)·사용자 확인 사실 컬럼

쪽 경계는 analyses.text 안의 폼피드(\\f)로 저장하므로 별도 컬럼이 필요 없다.

Revision ID: 0004
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS facts JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE analyses DROP COLUMN IF EXISTS facts")
