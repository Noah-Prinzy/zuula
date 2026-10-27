"""Phase 1.2: users.supabase_user_id links a Zuula account to its Supabase Auth user.

app/core/supabase_auth.py looks accounts up by the access token's `sub` first. Matching by
email or phone happens only once, on the first Supabase sign-in of an existing account, and
stores the `sub` here. After that, changing an email on the Supabase side keeps the same Zuula
account. Nullable and unique: legacy-only accounts have none, and one Supabase user maps to
one account.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("supabase_user_id", sa.Text(), nullable=True))
    op.create_unique_constraint(op.f("uq_users_supabase_user_id"), "users", ["supabase_user_id"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_supabase_user_id"), "users", type_="unique")
    op.drop_column("users", "supabase_user_id")
