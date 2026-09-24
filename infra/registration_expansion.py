"""One reviewed expansion, not a generic migration bypass.

Requires the compatible map reader already active. Leaves the additive schema
in place if application activation fails; never reverses or restores client data.
"""

import hashlib

COMPATIBLE_READER = "9d65102dec71755fe9a8224a11b73d070c3a9ed4"
MIGRATION = "apps/workspace/migrations/0009_simpler_registration.py"
MIGRATION_SHA256 = "56b3b18a108d23a606e6fa913b5b21accaeb204ca9eac6f62cdc2ac7eb350b3b"


def validate_source(release, previous, changes, run):
    migrations = [path for path in changes if "/migrations/" in path]
    if migrations != [MIGRATION]:
        raise RuntimeError("Only the reviewed registration expansion is allowed")
    source = (release / MIGRATION).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(source).hexdigest() != MIGRATION_SHA256:
        raise RuntimeError("Registration migration hash does not match review")
    run(
        ["git", "merge-base", "--is-ancestor", COMPATIBLE_READER, previous.name],
        cwd=release,
    )


def apply(root, release, values, run):
    # Refuse all unexpected migrations, including pre-existing pending changes.
    plan_check = (
        "from django.db import connection; "
        "from django.db.migrations.executor import MigrationExecutor; "
        "executor=MigrationExecutor(connection); "
        "plan=[(m.app_label,m.name,backwards) for m,backwards in executor.migration_plan(executor.loader.graph.leaf_nodes())]; "
        "assert plan == [('workspace','0009_simpler_registration',False)], 'Unexpected migration plan'; "
        "print('EXACT_REGISTRATION_EXPANSION_PLAN')"
    )
    owner_values = dict(values)
    owner_values["DATABASE_URL"] = (
        (root / "shared/secrets/migration-url").read_text().strip()
    )
    owner_values["PGOPTIONS"] = "-c lock_timeout=5s -c statement_timeout=60s"
    command = [release / ".venv/bin/python", "manage.py"]
    run(
        command + ["shell", "-c", plan_check],
        env=owner_values,
        user=root.name,
        cwd=release,
    )
    result = run(
        command + ["migrate", "workspace", "0009_simpler_registration", "--noinput"],
        env=owner_values,
        user=root.name,
        cwd=release,
    )
    print(result, flush=True)
    print("REGISTRATION_SCHEMA_EXPANDED_NO_DATA_REWRITE", flush=True)
