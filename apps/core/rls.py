"""Transaction-local database scope for HTTP and trusted background jobs."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from django.db import connection, transaction


@dataclass(frozen=True)
class DatabaseScope:
    tenant_id: str = ""
    campaign_id: str = ""
    actor_id: str = ""
    public_code: str = ""
    invitation_hash: str = ""


_scope = ContextVar("nabio_database_scope", default=DatabaseScope())
KEYS = tuple(DatabaseScope.__dataclass_fields__)


def current_scope():
    return _scope.get()


@contextmanager
def database_scope(*, campaign=None, actor=None, public_code="", invitation_hash=""):
    """Accept server-resolved objects, never identifiers copied from headers.

    SET LOCAL plus explicit restoration protects pooled connections and nested
    transactions. SQLite preserves transaction boundaries and Python scope,
    but does not emulate database-enforced RLS.
    """
    selected = DatabaseScope(
        tenant_id=str(UUID(str(campaign.tenant_id))) if campaign else "",
        campaign_id=str(UUID(str(campaign.pk))) if campaign else "",
        actor_id=str(int(actor.pk)) if actor and actor.is_authenticated else "",
        public_code=public_code[:180],
        invitation_hash=invitation_hash[:64],
    )
    token = _scope.set(selected)
    try:
        if connection.vendor != "postgresql":
            with transaction.atomic():
                yield selected
            return
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join("current_setting(%s, true)" for _ in KEYS),
                    [f"nabio.{key}" for key in KEYS],
                )
                previous = cursor.fetchone()
                for key in KEYS:
                    cursor.execute(
                        "SELECT set_config(%s, %s, true)",
                        [f"nabio.{key}", getattr(selected, key)],
                    )
            try:
                yield selected
            finally:
                if not connection.needs_rollback and connection.connection is not None:
                    with connection.cursor() as cursor:
                        for key, value in zip(KEYS, previous):
                            cursor.execute(
                                "SELECT set_config(%s, %s, true)",
                                [f"nabio.{key}", value or ""],
                            )
    finally:
        _scope.reset(token)


def verify_database_isolation():
    """Fail closed if runtime role can bypass RLS or any policy is missing."""
    from django.apps import apps
    from .rls_schema_v1 import policy_plan

    if connection.vendor != "postgresql":
        return False
    expected = policy_plan(apps, connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"
        )
        if any(cursor.fetchone()):
            return False
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb) AND pg_has_role(current_user, oid, 'MEMBER'))"
        )
        if cursor.fetchone()[0]:
            return False
        cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        if cursor.fetchone()[0]:
            return False
        for table, statements in expected.items():
            cursor.execute(
                "SELECT relrowsecurity, relforcerowsecurity, pg_has_role(current_user, relowner, 'MEMBER') FROM pg_class WHERE oid = to_regclass(%s)",
                [table],
            )
            row = cursor.fetchone()
            if row != (True, True, False):
                return False
            cursor.execute(
                "SELECT has_table_privilege(current_user, %s, 'TRUNCATE')", [table]
            )
            if cursor.fetchone()[0]:
                return False
            required = {
                statement.split()[2]
                for statement in statements
                if statement.startswith("CREATE POLICY")
            }
            cursor.execute(
                "SELECT polname FROM pg_policy WHERE polrelid = to_regclass(%s)",
                [table],
            )
            if {row[0] for row in cursor.fetchall()} != required:
                return False
    return True
