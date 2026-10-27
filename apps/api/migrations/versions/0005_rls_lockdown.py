"""Phase 1.5: row level security on every table, and no table access for Supabase's API roles.

On Supabase, PostgREST (`/rest/v1`) and Realtime reach the database as `anon` (publishable key)
or `authenticated` (a signed-in Supabase user). Zuula doesn't use either path for data: every
read and write goes through FastAPI, which connects as the tables' owner and so isn't subject
to RLS (it isn't FORCEd). This migration makes that the only way in:

- RLS on for every public table, with no policies: `anon`/`authenticated` see no rows.
- Revoke what Supabase's default privileges granted those roles. Notably TRUNCATE, which RLS
  doesn't cover.
- Revoke the same from tables future migrations create (default privileges for `postgres`).

Live updates (submission status, notifications, the home feed) will use Realtime Broadcast
sent by the API, not `postgres_changes`. That needs no table grants, works for anonymous
tracking ids, and keeps the partner API's keys and rate limits the only bulk read path.

The role statements only run where the roles exist, so local and test databases (plain
PostgreSQL) get just the RLS part.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_API_ROLES = "anon, authenticated"


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE t record;
        BEGIN
          FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
          END LOOP;
        END $$
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
             AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_API_ROLES};
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {_API_ROLES};
            ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
              REVOKE ALL ON TABLES FROM {_API_ROLES};
            ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
              REVOKE ALL ON SEQUENCES FROM {_API_ROLES};
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    # Turns RLS back off but leaves the grants revoked: re-granting anon would reopen the
    # tables to anyone holding the publishable key.
    op.execute(
        """
        DO $$
        DECLARE t record;
        BEGIN
          FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
            EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t.tablename);
          END LOOP;
        END $$
        """
    )
