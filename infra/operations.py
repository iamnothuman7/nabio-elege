"""Scoped backup, restore rehearsal and operational checks. No data is dropped."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

import first_install as deployment
from first_install import (
    ENVIRONMENTS,
    ORIGIN,
    check,
    environment,
    run,
    snapshot,
    sql,
    utc,
    write_new,
)


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def ensure_backup_key(root):
    private = root / "shared/secrets/backup-private.pem"
    public = root / "shared/secrets/backup-public.pem"
    if private.exists() != public.exists():
        raise RuntimeError("Incomplete backup key pair; no overwrite attempted")
    if not private.exists():
        run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:3072",
                "-sha256",
                "-nodes",
                "-keyout",
                private,
                "-out",
                public,
                "-days",
                "3650",
                "-subj",
                "/CN=Nabio Elege Backup/",
            ]
        )
        private.chmod(0o600)
        public.chmod(0o600)
    return private, public


def backup(root):
    _, public = ensure_backup_key(root)
    folder = snapshot(root, "complete")
    archive = folder / "complete.tar.gz"
    paths = {
        "database.dump": folder / "database.dump",
        "service.env": root / "shared/secrets/service.env",
        "migration-url": root / "shared/secrets/migration-url",
        "redis.conf": root / "shared/redis.conf",
        "clamd.conf": root / "shared/clamd.conf",
        "freshclam.conf": root / "shared/freshclam.conf",
        "install.json": root / "shared/install.json",
    }
    for path in (root / "shared/media").rglob("*"):
        if path.is_symlink():
            raise RuntimeError("Unexpected media symlink")
        if path.is_file():
            paths["media/" + str(path.relative_to(root / "shared/media"))] = path
    for unit in Path("/etc/systemd/system").glob(root.name + "-*.service"):
        paths["units/" + unit.name] = unit
    hashes = {name: digest(path) for name, path in paths.items()}
    with tarfile.open(archive, "x:gz") as tar:
        for name, path in paths.items():
            tar.add(path, arcname=name, recursive=False)
    archive.chmod(0o600)
    encrypted = folder / "complete.cms"
    run(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-cbc",
            "-in",
            archive,
            "-out",
            encrypted,
            "-outform",
            "DER",
            public,
        ]
    )
    encrypted.chmod(0o600)
    manifest = {
        "utc": utc(),
        "sha": (root / "current").resolve().name,
        "members": hashes,
        "archive_sha256": digest(archive),
        "encrypted_sha256": digest(encrypted),
        "encrypted_bytes": encrypted.stat().st_size,
    }
    write_new(folder / "complete-manifest.json", json.dumps(manifest, indent=2))
    # Only exact temporary files created by this invocation are removed.
    archive.unlink()
    (folder / "database.dump").unlink()
    print("ENCRYPTED_BACKUP_OK", folder.name, flush=True)
    return folder


def restore(root, folder):
    if folder.parent.resolve() != (root / "shared/backups").resolve():
        raise RuntimeError("Restore source outside this application")
    manifest = json.loads((folder / "complete-manifest.json").read_text())
    encrypted = folder / "complete.cms"
    if digest(encrypted) != manifest["encrypted_sha256"]:
        raise RuntimeError("Encrypted backup checksum mismatch")
    destination = root / "shared/backups" / ("restore-" + utc())
    destination.mkdir(mode=0o700)
    archive = destination / "verified.tar.gz"
    run(
        [
            "openssl",
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            encrypted,
            "-inkey",
            root / "shared/secrets/backup-private.pem",
            "-out",
            archive,
        ]
    )
    archive.chmod(0o600)
    if digest(archive) != manifest["archive_sha256"]:
        raise RuntimeError("Decrypted archive checksum mismatch")
    with tarfile.open(archive) as tar:
        if {m.name for m in tar.getmembers()} != set(manifest["members"]):
            raise RuntimeError("Unexpected archive content")
        for member in tar.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or not member.isfile():
                raise RuntimeError("Unsafe archive entry")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tar.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o600)
            if digest(target) != manifest["members"][member.name]:
                raise RuntimeError("Restored member checksum mismatch")
    database = root.name.replace("-", "_") + "_restore_" + utc().lower()
    if sql(f"SELECT datname FROM pg_database WHERE datname='{database}';").strip():
        raise RuntimeError("Restore database already exists")
    sql(f"CREATE DATABASE {database}; REVOKE ALL ON DATABASE {database} FROM PUBLIC;")
    with (destination / "database.dump").open("rb") as source:
        result = subprocess.run(
            [
                "runuser",
                "-u",
                "postgres",
                "--",
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "-d",
                database,
            ],
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
    if result.returncode:
        raise RuntimeError("Restore failed; isolated database preserved for diagnosis")
    source_db = root.name.replace("-", "_")
    for query in (
        "SELECT count(*) FROM django_migrations;",
        "SELECT count(*) FROM pg_class WHERE relrowsecurity AND relforcerowsecurity AND relnamespace='public'::regnamespace;",
        "SELECT count(*) FROM auth_user;",
        "SELECT count(*) FROM campaigns_campaign;",
    ):
        if sql(query, source_db) != sql(query, database):
            raise RuntimeError("Restore verification mismatch")
    result = {
        "utc": utc(),
        "sha": manifest["sha"],
        "backup": folder.name,
        "restore_database": database,
        "file_hashes_verified": len(manifest["members"]),
        "migrations_counts_rls_verified": True,
        "preserved": True,
    }
    write_new(destination / "restore-result.json", json.dumps(result, indent=2))
    write_new(root / f"shared/restore-passed-{utc()}.json", json.dumps(result))
    print("FULL_RESTORE_OK", json.dumps(result), flush=True)


def stage_revision(root, sha):
    if root.name != "nabio-elege-staging" or not re.fullmatch("[a-f0-9]{40}", sha):
        raise RuntimeError("Preactivation revision update is staging-only")
    if (
        run(
            ["systemctl", "show", root.name + "-web", "--value", "--property=MainPID"]
        ).strip()
        != "0"
    ):
        raise RuntimeError(
            "Stop: staging already active; this is not a rolling updater"
        )
    previous = (root / "current").resolve()
    release = root / "releases" / sha
    if release.exists():
        raise RuntimeError("Existing revision directory")
    snapshot(root, "before-infra-revision")
    run(["git", "clone", "--no-checkout", ORIGIN, release])
    run(["git", "checkout", "--detach", sha], cwd=release)
    changes = run(
        ["git", "diff", "--name-only", previous.name, sha], cwd=release
    ).splitlines()
    if not all(p.startswith(("infra/", "docs/")) for p in changes):
        raise RuntimeError("Application changes need full separate upgrade procedure")
    if (release / "requirements-production.lock").read_bytes() != (
        previous / "requirements-production.lock"
    ).read_bytes():
        raise RuntimeError("Dependency changes")
    (release / ".venv").symlink_to(previous / ".venv", target_is_directory=True)
    (release / ".git").chmod(0o700)
    link = root / "current.next"
    link.symlink_to(release, target_is_directory=True)
    link.replace(root / "current")
    state_path = root / "shared/install.json"
    state = json.loads(state_path.read_text())
    state.update(sha=sha, previous_sha=previous.name, updated_utc=utc())
    state_path.write_text(json.dumps(state))
    print("STAGING_INFRA_REVISION_READY", sha, flush=True)


def timers(root):
    py = root / "current/.venv/bin/python"
    app_env = json.loads((root / "shared/install.json").read_text())["environment"]
    for purpose, schedule in (
        ("backup", "OnCalendar=*-*-* 03:20:00\nRandomizedDelaySec=600"),
        ("monitor", "OnBootSec=3min\nOnUnitActiveSec=5min"),
    ):
        service = f"{root.name}-{purpose}"
        action = "backup" if purpose == "backup" else "monitor"
        write_new(
            f"/etc/systemd/system/{service}.service",
            f"""[Unit]
Description=Nabio Elege {purpose}
After=network.target postgresql.service
[Service]
Type=oneshot
UMask=0077
ExecStart={py} {root}/current/infra/operations.py {action} {app_env}
TimeoutStartSec=900
PrivateTmp=true
ProtectHome=true
Nice=10
""",
            0o644,
        )
        write_new(
            f"/etc/systemd/system/{service}.timer",
            f"""[Unit]
Description=Nabio Elege {purpose} timer
[Timer]
{schedule}
Persistent=true
[Install]
WantedBy=timers.target
""",
            0o644,
        )
    run(["systemctl", "daemon-reload"])
    run(
        [
            "systemctl",
            "enable",
            "--now",
            root.name + "-backup.timer",
            root.name + "-monitor.timer",
        ]
    )
    print("BACKUP_AND_MONITOR_TIMERS_ENABLED", flush=True)


def monitor(root):
    check(root, root.name, verify_baseline=False)
    if shutil.disk_usage(root).free < 5 * 1024**3:
        raise RuntimeError("Less than 5 GiB available")
    backups = sorted((root / "shared/backups").glob("*/complete-manifest.json"))
    if not backups:
        raise RuntimeError("Missing complete encrypted backup")
    import time

    if time.time() - backups[-1].stat().st_mtime > 36 * 3600:
        raise RuntimeError("Complete backup older than 36 hours")
    run(
        [
            "openssl",
            "x509",
            "-checkend",
            str(14 * 86400),
            "-noout",
            "-in",
            "/etc/letsencrypt/live/elege.nabio.pro/cert.pem",
        ]
    )
    print("OPERATIONS_MONITOR_OK", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("backup", "restore", "stage-revision", "timers", "monitor")
    )
    parser.add_argument("environment", choices=ENVIRONMENTS)
    parser.add_argument("--sha")
    parser.add_argument("--backup")
    args = parser.parse_args()
    root = Path("/var/www/apps") / ENVIRONMENTS[args.environment][0]
    if (
        os.geteuid() != 0
        or root.is_symlink()
        or root.parent.resolve() != Path("/var/www/apps")
    ):
        raise RuntimeError("Unexpected privilege or target")
    deployment.DIAGNOSTIC_ROOT = root
    try:
        if args.action == "backup":
            backup(root)
        elif args.action == "restore":
            restore(root, root / "shared/backups" / args.backup)
        elif args.action == "stage-revision":
            stage_revision(root, args.sha)
        elif args.action == "timers":
            timers(root)
        elif args.action == "monitor":
            monitor(root)
    except Exception as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        sys.exit(1)
