"""First-time, non-public QA provisioning. Refuses all pre-existing target resources.

Run on the authorized Linux host as an administrator, only after its read-only
inventory. This never starts web services, changes Nginx or drops databases.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path("/var/www/apps/nabio-elege-qa")
ACCOUNT = "nabio-elege-qa"
ROLE = "nabio_elege_qa"
DATABASES = ("nabio_elege_qa", "test_nabio_elege_qa")
ORIGIN = "https://github.com/iamnothuman7/nabio-elege.git"


def plan(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A complete tested commit SHA is required")
    return {"commit": commit, "root": ROOT.as_posix(), "account": ACCOUNT, "role": ROLE, "databases": DATABASES, "public_port": None}


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=kwargs.pop("timeout", 60), **kwargs)


def postgres(sql):
    # SQL stays on stdin, never in process arguments or diagnostics.
    result = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-v", "ON_ERROR_STOP=1", "-At"], input=sql, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("PostgreSQL administrative step failed; secrets withheld")
    return result.stdout.strip()


def validation_database(commit):
    plan(commit)
    return "test_nabio_elege_qa_" + commit[:12]


def validate_existing(commit):
    """Validate a new immutable revision without reusing or deleting test data."""
    plan(commit)
    if os.geteuid() != 0:
        raise RuntimeError("Administrative account required for an exclusive test database")
    import pwd
    from urllib.parse import urlsplit

    account = pwd.getpwnam(ACCOUNT)
    if ROOT.is_symlink() or ROOT.resolve() != ROOT or ROOT.stat().st_uid != 0:
        raise RuntimeError("Unexpected QA directory ownership or target")
    credentials = ROOT / "shared/qa-environment.json"
    if credentials.is_symlink() or credentials.resolve().parent != ROOT / "shared":
        raise RuntimeError("Unexpected QA configuration target")
    if credentials.stat().st_uid != account.pw_uid or credentials.stat().st_mode & 0o077:
        raise RuntimeError("QA credentials must be private and owned by the QA account")
    environment = json.loads(credentials.read_text())
    if set(environment) != {"SECRET_KEY", "TEST_DATABASE_URL", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE"}:
        raise RuntimeError("Unexpected QA environment fields")
    connection = urlsplit(environment["TEST_DATABASE_URL"])
    if (connection.scheme, connection.hostname, connection.port, connection.username, connection.path) != ("postgresql", "127.0.0.1", 5432, ROLE, "/nabio_elege_qa"):
        raise RuntimeError("QA database target mismatch")
    privileges = postgres("SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname='nabio_elege_qa';")
    if privileges != "f":
        raise RuntimeError("Unexpected QA role privileges")
    database = validation_database(commit)
    release = ROOT / "releases" / commit
    if release.exists() or release.is_symlink() or postgres(f"SELECT datname FROM pg_database WHERE datname='{database}';"):
        raise RuntimeError("Validation revision already exists; preserve it and inspect")

    # Only new, strictly generated QA identifiers are accepted here.
    postgres(f"CREATE DATABASE {database} OWNER {ROLE};")
    postgres(f"REVOKE ALL ON DATABASE {database} FROM PUBLIC; GRANT CONNECT ON DATABASE {database} TO {ROLE};")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / "shared/backups" / f"{database}-{stamp}.dump"
    with os.fdopen(os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as output:
        run(["runuser", "-u", "postgres", "--", "pg_dump", "--format=custom", "--no-owner", "--no-privileges", database], stdout=output, stderr=subprocess.PIPE)
    run(["pg_restore", "--list", str(backup)], capture_output=True)
    print(json.dumps({"backup_before_test_migrations": {"database": database, "file": str(backup), "bytes": backup.stat().st_size, "sha256": hashlib.sha256(backup.read_bytes()).hexdigest()}}), flush=True)
    run(["git", "clone", "--no-checkout", ORIGIN, str(release)], timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    run(["git", "-C", str(release), "checkout", "--detach", commit], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    actual = run(["git", "-C", str(release), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if actual != commit:
        raise RuntimeError("Release hash mismatch")
    command = ["runuser", "-u", ACCOUNT, "--", str(ROOT / "venv/bin/python")]
    run([*command, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "-r", str(release / "requirements-production.txt")], timeout=600)
    env = {**os.environ, **environment, "TEST_DATABASE_NAME": database}
    env.pop("APP_ENV", None)
    print(json.dumps({"step": "postgresql-tests", "commit": commit, "database": database, "destructive_drop": False}), flush=True)
    result = subprocess.run([*command, "manage.py", "test", "--keepdb", "--noinput", "--settings=nabio_elege.postgres_test_settings"], cwd=release, env=env, timeout=600)
    print(json.dumps({"test_exit_code": result.returncode, "public_services_created": False}), flush=True)
    return result.returncode


def provision(commit):
    state = plan(commit)
    if os.geteuid() != 0:
        raise RuntimeError("Administrative account required for isolated resource creation")
    import pwd
    if ROOT.exists() or ROOT.is_symlink():
        raise RuntimeError("QA directory exists; inspect it instead of overwriting")
    try:
        pwd.getpwnam(ACCOUNT)
    except KeyError:
        pass
    else:
        raise RuntimeError("QA account exists; inspect ownership before continuing")
    conflicts = postgres("SELECT datname FROM pg_database WHERE datname IN ('nabio_elege_qa', 'test_nabio_elege_qa'); SELECT rolname FROM pg_roles WHERE rolname='nabio_elege_qa';")
    if conflicts:
        raise RuntimeError("QA database or role already exists; no resource changed")
    for executable in ["python3.12", "git", "runuser", "psql", "pg_dump", "pg_restore", "useradd"]:
        if not shutil.which(executable):
            raise RuntimeError("Required executable missing: " + executable)
    run(["python3.12", "-c", "import venv, ensurepip"], capture_output=True)
    print(json.dumps({"preflight": "passed", **state}), flush=True)

    run(["useradd", "--system", "--user-group", "--home-dir", str(ROOT), "--shell", "/usr/sbin/nologin", ACCOUNT], capture_output=True)
    account = pwd.getpwnam(ACCOUNT)
    ROOT.mkdir(mode=0o750)
    os.chown(ROOT, 0, account.pw_gid)
    for name in ["releases", "shared", "shared/backups", "shared/logs"]:
        path = ROOT / name
        path.mkdir(mode=0o750)
        os.chown(path, 0 if name == "releases" else account.pw_uid, account.pw_gid)

    password = secrets.token_urlsafe(48)
    postgres("SET password_encryption='scram-sha-256'; CREATE ROLE nabio_elege_qa LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '" + password + "';")
    for database in DATABASES:
        postgres(f"CREATE DATABASE {database} OWNER nabio_elege_qa;")
        # Narrow only the new databases, never change a pre-existing database.
        postgres(f"REVOKE ALL ON DATABASE {database} FROM PUBLIC; GRANT CONNECT ON DATABASE {database} TO nabio_elege_qa;")
    environment = {"SECRET_KEY": secrets.token_urlsafe(64), "TEST_DATABASE_URL": f"postgresql://{ROLE}:{password}@127.0.0.1:5432/nabio_elege_qa", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    credentials_path = ROOT / "shared/qa-environment.json"
    with os.fdopen(os.open(credentials_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as output:
        json.dump(environment, output)
    os.chown(credentials_path, account.pw_uid, account.pw_gid)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups = []
    for database in DATABASES:
        path = ROOT / "shared/backups" / f"{database}-{stamp}-{commit[:12]}.dump"
        with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as output:
            run(["runuser", "-u", "postgres", "--", "pg_dump", "--format=custom", "--no-owner", "--no-privileges", database], stdout=output, stderr=subprocess.PIPE)
        run(["pg_restore", "--list", str(path)], capture_output=True)
        backups.append({"database": database, "file": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    print(json.dumps({"backup_before_test_migrations": backups, "note": "Empty dedicated databases; archive structure verified, restore drill still pending"}), flush=True)

    release = ROOT / "releases" / commit
    run(["git", "clone", "--no-checkout", ORIGIN, str(release)], timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    run(["git", "-C", str(release), "checkout", "--detach", commit], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    actual = run(["git", "-C", str(release), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if actual != commit:
        raise RuntimeError("Release hash mismatch")
    venv = ROOT / "venv"
    venv.mkdir(mode=0o750)
    os.chown(venv, account.pw_uid, account.pw_gid)
    run(["runuser", "-u", ACCOUNT, "--", "python3.12", "-m", "venv", str(venv)], timeout=120)
    python = str(venv / "bin/python")
    command = ["runuser", "-u", ACCOUNT, "--", python]
    run([*command, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "-r", str(release / "requirements-production.txt")], timeout=600)
    env = {**os.environ, **environment}
    env.pop("APP_ENV", None)
    print(json.dumps({"step": "postgresql-tests", "release": str(release), "database": "test_nabio_elege_qa", "destructive_drop": False}), flush=True)
    result = subprocess.run([*command, "manage.py", "test", "--keepdb", "--noinput", "--settings=nabio_elege.postgres_test_settings"], cwd=release, env=env, timeout=600)
    print(json.dumps({"test_exit_code": result.returncode, "public_services_created": False}), flush=True)
    return result.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--existing", action="store_true", help="Validate a new revision in the previously provisioned exclusive QA environment")
    args = parser.parse_args()
    try:
        sys.exit(validate_existing(args.commit) if args.existing else provision(args.commit))
    except Exception as exc:
        # Do not dump environment, SQL, credentials or arbitrary provider messages.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "instruction": "Inspect the exclusive QA resources; do not delete or blindly rerun"}), flush=True)
        sys.exit(1)
