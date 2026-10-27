"""Phase 1.2: deleting a Supabase Auth user unlinks its Zuula account.

users.supabase_user_id (0006) holds the Supabase user's id. If that user is deleted in
Supabase (dashboard or admin API), the id would dangle, and signing up again with the same
email would be refused: app/core/supabase_auth.py never re-links an account that is linked to a
different Supabase user. This trigger clears the link instead, so the next Supabase sign-in
with that email links the account again. The Zuula account itself, with its ratings and audit
history, is kept.

SECURITY DEFINER because Supabase deletes auth users as `supabase_auth_admin`, which can't
write public.users; search_path is empty and every name is schema-qualified. EXECUTE is
revoked from everyone else; a trigger function can't be called directly anyway.

Plain PostgreSQL (local and test databases) has no `auth` schema, so the migration does nothing
there.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('auth.users') IS NULL THEN
            RETURN;
          END IF;

          CREATE OR REPLACE FUNCTION public.unlink_deleted_supabase_user()
          RETURNS trigger
          LANGUAGE plpgsql
          SECURITY DEFINER
          SET search_path = ''
          AS $fn$
          BEGIN
            UPDATE public.users SET supabase_user_id = NULL WHERE supabase_user_id = OLD.id::text;
            RETURN OLD;
          END
          $fn$;

          REVOKE ALL ON FUNCTION public.unlink_deleted_supabase_user() FROM PUBLIC;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON FUNCTION public.unlink_deleted_supabase_user() FROM anon, authenticated;
          END IF;

          DROP TRIGGER IF EXISTS unlink_zuula_account ON auth.users;
          CREATE TRIGGER unlink_zuula_account
            AFTER DELETE ON auth.users
            FOR EACH ROW EXECUTE FUNCTION public.unlink_deleted_supabase_user();
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('auth.users') IS NOT NULL THEN
            DROP TRIGGER IF EXISTS unlink_zuula_account ON auth.users;
          END IF;
          DROP FUNCTION IF EXISTS public.unlink_deleted_supabase_user();
        END $$
        """
    )
