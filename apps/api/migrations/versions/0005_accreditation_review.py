"""Admin review of accreditation applications (FR-AUTH-02).

- accreditation_applications.requested_role: the role an application asks for (Verified
  Journalist or Expert Reviewer). Existing applications were all journalist applications.
- audit_log.action gains `accreditation.approve` and `accreditation.reject`: an admin's
  decision on an application is its own audited action.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ACTIONS_0003 = (
    "verdict.override",
    "verdict.confirm",
    "user.role_change",
    "user.suspend",
    "source.add",
    "source.deactivate",
    "broadcast.send",
    "settings.update",
    "moderation.remove",
    "user.reinstate",
    "ratings.exclude",
)
_ACTIONS_0005 = (*_ACTIONS_0003, "accreditation.approve", "accreditation.reject")


def _action_check(actions: tuple[str, ...]) -> str:
    return "action IN ({})".format(", ".join(f"'{a}'" for a in actions))


def upgrade() -> None:
    op.add_column(
        "accreditation_applications",
        sa.Column("requested_role", sa.Text(), server_default="journalist", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_accreditation_applications_requested_role"),
        "accreditation_applications",
        "requested_role IN ('journalist', 'expert')",
    )
    op.drop_constraint(op.f("ck_audit_log_action"), "audit_log", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_log_action"), "audit_log", _action_check(_ACTIONS_0005)
    )


def downgrade() -> None:
    # Fails if an accreditation decision has been audited: audit_log is append-only, so those
    # entries can't be removed to fit the older constraint.
    op.drop_constraint(op.f("ck_audit_log_action"), "audit_log", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_log_action"), "audit_log", _action_check(_ACTIONS_0003)
    )
    op.drop_constraint(
        op.f("ck_accreditation_applications_requested_role"),
        "accreditation_applications",
        type_="check",
    )
    op.drop_column("accreditation_applications", "requested_role")
