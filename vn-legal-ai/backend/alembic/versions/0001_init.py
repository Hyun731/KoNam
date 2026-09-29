"""법령 지식베이스 초기 스키마

Revision ID: 0001
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _run(sql: str) -> None:
    # asyncpg는 한 번에 여러 문장을 실행하지 못하므로 나눠서 보낸다
    for stmt in sql.split(";"):
        if stmt.strip():
            op.execute(stmt)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _run(
        """
        CREATE TABLE legal_documents (
            id              TEXT PRIMARY KEY,
            doc_type        TEXT NOT NULL,
            title_vi        TEXT NOT NULL,
            title_ko        TEXT,
            short_names     TEXT[] NOT NULL DEFAULT '{}',
            issuer          TEXT,
            issued_date     DATE,
            effective_from  DATE,
            effective_to    DATE,
            status          TEXT NOT NULL DEFAULT 'con_hieu_luc',
            source_url      TEXT,
            domains         TEXT[] NOT NULL DEFAULT '{}',
            raw_hash        TEXT,
            is_sample       BOOLEAN NOT NULL DEFAULT false,
            preamble        TEXT,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE document_relations (
            src_doc  TEXT NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
            dst_doc  TEXT NOT NULL,
            rel      TEXT NOT NULL,
            PRIMARY KEY (src_doc, dst_doc, rel)
        );

        CREATE TABLE provisions (
            id              TEXT PRIMARY KEY,
            document_id     TEXT NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
            parent_id       TEXT,
            dieu_id         TEXT,
            level           TEXT NOT NULL,
            number          TEXT NOT NULL,
            heading         TEXT,
            text_vi         TEXT NOT NULL DEFAULT '',
            full_text_vi    TEXT NOT NULL DEFAULT '',
            path            TEXT NOT NULL,
            ordinal         INTEGER NOT NULL,
            effective_from  DATE,
            effective_to    DATE
        );
        CREATE INDEX ix_provisions_document_id ON provisions (document_id);
        CREATE INDEX ix_provisions_dieu_id ON provisions (dieu_id);

        CREATE TABLE chunks (
            id            BIGSERIAL PRIMARY KEY,
            provision_id  TEXT NOT NULL REFERENCES provisions(id) ON DELETE CASCADE,
            dieu_id       TEXT NOT NULL,
            document_id   TEXT NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
            kind          TEXT NOT NULL,
            lang          TEXT NOT NULL,
            content       TEXT NOT NULL,
            tokens        TEXT,
            tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(tokens, content))) STORED,
            embedding     vector(1536),
            domains       TEXT[] NOT NULL DEFAULT '{}'
        );
        CREATE INDEX ix_chunks_dieu_id ON chunks (dieu_id);
        CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv);
        CREATE INDEX ix_chunks_domains ON chunks USING gin (domains);
        CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);

        CREATE TABLE provision_edges (
            src_id      TEXT NOT NULL REFERENCES provisions(id) ON DELETE CASCADE,
            dst_id      TEXT NOT NULL REFERENCES provisions(id) ON DELETE CASCADE,
            rel         TEXT NOT NULL,
            evidence    TEXT,
            method      TEXT NOT NULL DEFAULT 'rule',
            confidence  REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (src_id, dst_id, rel)
        );
        CREATE INDEX ix_provision_edges_dst_id ON provision_edges (dst_id);

        CREATE TABLE unresolved_references (
            id        BIGSERIAL PRIMARY KEY,
            src_id    TEXT NOT NULL REFERENCES provisions(id) ON DELETE CASCADE,
            evidence  TEXT NOT NULL,
            reason    TEXT NOT NULL
        );
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS unresolved_references;
        DROP TABLE IF EXISTS provision_edges;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS provisions;
        DROP TABLE IF EXISTS document_relations;
        DROP TABLE IF EXISTS legal_documents;
        """
    )
