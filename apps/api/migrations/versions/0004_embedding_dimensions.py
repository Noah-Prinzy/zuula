"""P4: fact_check_reports.embedding gets a fixed dimension and an HNSW index.

P3 shipped the column as an untyped `vector` (ADR 0002 §1's note that "the embedding model is
P4's choice"), with similarity search an exact scan over the (small) table. P4 picks
all-MiniLM-L6-v2 (app/providers/embedding.py) for the dedupe check in
app/providers/analysis.py's GroqAnalysisProvider as well as the existing FR-SEARCH-03 related-
reports feature — both now share the same embedding. 384 dimensions, cosine distance (the
model is trained for cosine/dot-product similarity, not Euclidean), HNSW so the nearest-
neighbor query stays fast as the table grows past what an exact scan can keep up with. No
existing row has `embedding` set yet, so there's nothing to backfill or re-cast.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE fact_check_reports ALTER COLUMN embedding TYPE vector(384)")
    op.create_index(
        "ix_fact_check_reports_embedding_hnsw",
        "fact_check_reports",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_fact_check_reports_embedding_hnsw", table_name="fact_check_reports")
    op.execute("ALTER TABLE fact_check_reports ALTER COLUMN embedding TYPE vector")
