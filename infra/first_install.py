"""Explicit, first-install-only provisioner for an audited Ubuntu host.

Never upgrades packages, changes SSH/firewall/shared Redis, drops databases,
overwrites an existing application, or starts an application as root.
Run from an approved Git revision. Operational state stays outside Git.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

DOMAIN = "elege.nabio.pro"
ORIGIN = "https://github.com/iamnothuman7/nabio-elege.git"
DIAGNOSTIC_ROOT = None
ENVIRONMENTS = {
    "staging": ("nabio-elege-staging", 8091, 6391, 3391),
    "production": ("nabio-elege", 8090, 6390, 3390),
}


def run(args, *, env=None, user=None, cwd=None, data=None, timeout=900):
    kwargs = {}
    if user:
        account = pwd.getpwnam(user)
        kwargs.update(user=account.pw_uid, group=account.pw_gid, extra_groups=[])
    result = subprocess.run(
        [str(x) for x in args],
        input=data,
        text=True,
        capture_output=True,
        env=env,
        cwd=cwd,
        timeout=timeout,
        **kwargs,
    )
    if result.returncode:
        if DIAGNOSTIC_ROOT and (DIAGNOSTIC_ROOT / "shared/secrets").is_dir():
            diagnostic = (
                DIAGNOSTIC_ROOT
                / "shared/secrets"
                / f"failure-{utc()}-{secrets.token_hex(3)}.txt"
            )
            write_new(diagnostic, result.stdout + "\n" + result.stderr)
        # Connection strings and provider errors must not reach a terminal/log.
        raise RuntimeError(
            f"Command failed: {Path(str(args[0])).name}; exit={result.returncode}"
        )
    return result.stdout


def write_new(path, content, mode=0o600, group=None):
    path = Path(path)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(mode)
    if group:
        shutil.chown(path, group=group)


def utc():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sql(statement, database="postgres"):
    return run(
        [
            "runuser",
            "-u",
            "postgres",
            "--",
            "psql",
            "-X",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            database,
        ],
        data=statement,
    )


def environment(root):
    values = dict(os.environ)
    for line in (root / "shared/secrets/service.env").read_text().splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


def manage(root, *args, owner=False):
    values = environment(root)
    if owner:
        values["DATABASE_URL"] = (
            (root / "shared/secrets/migration-url").read_text().strip()
        )
    return run(
        [root / "current/.venv/bin/python", "manage.py", *args],
        env=values,
        user=root.name,
        cwd=root / "current",
    )


def baseline():
    hashes = {}
    for folder in (
        "/etc/nginx/sites-available",
        "/etc/nginx/sites-enabled",
        "/etc/nginx/conf.d",
    ):
        for path in Path(folder).glob("*"):
            if path.name == DOMAIN:
                continue
            if path.is_file():
                hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    pids = {}
    for name in ("nginx", "jumbi", "amparo", "portalverdadeceara"):
        pids[name] = run(
            ["systemctl", "show", name, "--value", "--property=MainPID"]
        ).strip()
    return {"nginx_hashes": hashes, "service_pids": pids, "utc": utc()}


def assert_baseline(root):
    before = json.loads((root / "shared/initial-baseline.json").read_text())
    after = baseline()
    for path, digest in before["nginx_hashes"].items():
        if after["nginx_hashes"].get(path) != digest:
            raise RuntimeError(
                "Unrelated nginx file changed; investigate before continuing"
            )
    for name, pid in before["service_pids"].items():
        if after["service_pids"].get(name) != pid:
            raise RuntimeError(
                "Unrelated service PID changed; investigate before continuing"
            )
    print("BASELINE_UNCHANGED", flush=True)


def init(root, name, web, redis_port, av, sha, app_env):
    if root.exists() or root.is_symlink():
        raise RuntimeError("Existing root: first-install refuses overwrite")
    try:
        pwd.getpwnam(name)
    except KeyError:
        pass
    else:
        raise RuntimeError("Existing system account")
    prefix = name.replace("-", "_")
    for port in (web, redis_port, av):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    for unit in ("web", "worker", "beat", "redis", "av", "freshclam"):
        if Path(f"/etc/systemd/system/{name}-{unit}.service").exists():
            raise RuntimeError("Existing unit")
    if sql(f"SELECT datname FROM pg_database WHERE datname='{prefix}';").strip():
        raise RuntimeError("Existing database")
    if sql(
        f"SELECT rolname FROM pg_roles WHERE rolname IN ('{prefix}_owner','{prefix}_runtime');"
    ).strip():
        raise RuntimeError("Existing roles")
    before = baseline()
    root.mkdir(mode=0o755)
    (root / "shared").mkdir(mode=0o755)
    write_new(root / "shared/initial-baseline.json", json.dumps(before, indent=2))
    write_new(
        root / "shared/install.json",
        json.dumps(
            {
                "sha": sha,
                "environment": app_env,
                "started_utc": utc(),
                "approval": "Owner reviewed and authorized fixes/deployment in the task conversation.",
                "first_install": True,
            }
        ),
    )
    run(
        [
            "useradd",
            "--system",
            "--user-group",
            "--home-dir",
            root,
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            name,
        ]
    )
    for folder in ("media", "logs", "redis", "av-data", "av-tmp", "beat"):
        target = root / "shared" / folder
        target.mkdir(mode=0o700)
        shutil.chown(target, user=name, group=name)
    for folder, mode in (
        ("secrets", 0o700),
        ("backups", 0o700),
        ("staticfiles", 0o755),
        ("acme", 0o755),
    ):
        (root / "shared" / folder).mkdir(mode=mode)
    (root / "releases").mkdir(mode=0o755)
    print("DIRECTORIES_AND_ACCOUNT_CREATED", flush=True)
    release = root / "releases" / sha
    run(["git", "clone", "--no-checkout", ORIGIN, release])
    run(["git", "checkout", "--detach", sha], cwd=release)
    if run(["git", "rev-parse", "HEAD"], cwd=release).strip() != sha:
        raise RuntimeError("Unexpected revision")
    run(["/usr/bin/python3.12", "-m", "venv", release / ".venv"])
    py = release / ".venv/bin/python"
    run([py, "infra/check_dependency_lock.py"], cwd=release)
    run([py, "-m", "pip", "install", "-r", "requirements-production.lock"], cwd=release)
    run([py, "-m", "pip", "check"], cwd=release)
    (root / "current").symlink_to(release, target_is_directory=True)
    # Git metadata is operational only, never writable by the runtime.
    (release / ".git").chmod(0o700)
    print("LOCKED_RELEASE_INSTALLED", flush=True)
    owner_secret, runtime_secret, redis_secret = (
        secrets.token_urlsafe(48) for _ in range(3)
    )
    # Generated values are URL-safe. SQL input travels over stdin, never argv.
    sql(
        f"CREATE ROLE {prefix}_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{owner_secret}';\n"
        f"CREATE ROLE {prefix}_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{runtime_secret}';\n"
        f"CREATE DATABASE {prefix} OWNER {prefix}_owner;\n"
        f"REVOKE ALL ON DATABASE {prefix} FROM PUBLIC;\n"
        f"GRANT CONNECT ON DATABASE {prefix} TO {prefix}_owner, {prefix}_runtime;"
    )
    sql(
        f"REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE, CREATE ON SCHEMA public TO {prefix}_owner; GRANT USAGE ON SCHEMA public TO {prefix}_runtime;",
        prefix,
    )
    encryption_key = run(
        [
            py,
            "-c",
            "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())",
        ]
    ).strip()
    values = {
        "DJANGO_SETTINGS_MODULE": "nabio_elege.production_settings",
        "APP_ENV": app_env,
        "SECRET_KEY": secrets.token_urlsafe(64),
        "FIELD_ENCRYPTION_KEY": encryption_key,
        "BLIND_INDEX_KEY": secrets.token_urlsafe(48),
        "RECEIPT_TOKEN_KEY": secrets.token_urlsafe(48),
        "DATABASE_URL": f"postgresql://{prefix}_runtime:{runtime_secret}@127.0.0.1:5432/{prefix}",
        "REDIS_URL": f"redis://:{redis_secret}@127.0.0.1:{redis_port}/0",
        "CACHE_URL": f"redis://:{redis_secret}@127.0.0.1:{redis_port}/1",
        "ALLOWED_HOSTS": DOMAIN,
        "CSRF_TRUSTED_ORIGINS": f"https://{DOMAIN}"
        + (f",https://{DOMAIN}:8449" if app_env == "staging" else ""),
        "MEDIA_ROOT": str(root / "shared/media"),
        "STATIC_ROOT": str(root / "shared/staticfiles"),
        "CLAMAV_HOST": "127.0.0.1",
        "CLAMAV_PORT": str(av),
        "TRUST_PROXY_HEADERS": "True",
        "TRUSTED_PROXY_IPS": "127.0.0.1,::1",
        "SECURE_HSTS_SECONDS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    write_new(
        root / "shared/secrets/service.env",
        "".join(f"{key}={value}\n" for key, value in values.items()),
    )
    write_new(
        root / "shared/secrets/migration-url",
        f"postgresql://{prefix}_owner:{owner_secret}@127.0.0.1:5432/{prefix}",
    )
    write_new(
        root / "shared/redis.conf",
        f"bind 127.0.0.1\nport {redis_port}\nprotected-mode yes\nrequirepass {redis_secret}\ndir {root}/shared/redis\nappendonly yes\nappendfsync everysec\nmaxmemory 128mb\nmaxmemory-policy noeviction\nsave 900 1\n",
        0o640,
        name,
    )
    write_new(
        root / "shared/clamd.conf",
        f"Foreground yes\nDatabaseDirectory {root}/shared/av-data\nCVDCertsDirectory {root}/vendor/etc/clamav/certs\nTemporaryDirectory {root}/shared/av-tmp\nTCPAddr 127.0.0.1\nTCPSocket {av}\nStreamMaxLength 22M\nMaxThreads 2\nMaxQueue 8\nConcurrentDatabaseReload no\nLogTime yes\n",
        0o644,
    )
    write_new(
        root / "shared/freshclam.conf",
        f"DatabaseDirectory {root}/shared/av-data\nCVDCertsDirectory {root}/vendor/etc/clamav/certs\nDatabaseOwner {name}\nDatabaseMirror database.clamav.net\nForeground yes\nChecks 12\nNotifyClamd {root}/shared/clamd.conf\n",
        0o644,
    )
    print("ISOLATED_DATABASE_AND_SECRETS_CREATED", flush=True)
    assert_baseline(root)


def antivirus(root, name):
    vendor = root / "vendor"
    vendor.mkdir(mode=0o755)
    packages = vendor / "packages"
    packages.mkdir(mode=0o755)
    # Extract official signed-APT-index packages only into this project.
    # No dpkg installation, package maintainer scripts, or global service starts.
    specs = ["clamav-base", "clamav-daemon", "clamav-freshclam", "libclamav12"]
    run(["apt-get", "download", *specs], cwd=packages)
    hashes = {}
    for deb in sorted(packages.glob("*.deb")):
        hashes[deb.name] = hashlib.sha256(deb.read_bytes()).hexdigest()
        run(["dpkg-deb", "-x", deb, vendor])
    write_new(vendor / "package-sha256.json", json.dumps(hashes, indent=2))
    values = dict(os.environ, LD_LIBRARY_PATH=str(vendor / "usr/lib/x86_64-linux-gnu"))
    for binary in ("sbin/clamd", "bin/freshclam"):
        output = run(["ldd", vendor / "usr" / binary], env=values)
        if "not found" in output:
            raise RuntimeError("ClamAV dependency missing: no global install attempted")
    print("ANTIVIRUS_BINARIES_VERIFIED", flush=True)
    run(
        [vendor / "usr/bin/freshclam", f"--config-file={root}/shared/freshclam.conf"],
        env=values,
        user=name,
        timeout=900,
    )
    print("ANTIVIRUS_SIGNATURES_UPDATED", flush=True)


def snapshot(root, label):
    folder = root / "shared/backups" / f"{utc()}-{label}"
    folder.mkdir(mode=0o700)
    db = root.name.replace("-", "_")
    # Dump through peer-authenticated postgres into root-owned stdout file.
    dump = folder / "database.dump"
    with dump.open("xb") as handle:
        result = subprocess.run(
            [
                "runuser",
                "-u",
                "postgres",
                "--",
                "pg_dump",
                "-Fc",
                "--no-owner",
                "--no-privileges",
                db,
            ],
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=300,
        )
    dump.chmod(0o600)
    if result.returncode:
        raise RuntimeError("Backup failed")
    run(["pg_restore", "--list", dump])
    manifest = {
        "utc": utc(),
        "sha": (root / "current").resolve().name,
        "size": dump.stat().st_size,
        "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
    }
    write_new(folder / "manifest.json", json.dumps(manifest, indent=2))
    print(f"VERIFIED_BACKUP {folder.name}", flush=True)
    return folder


def migrate(root, name):
    snapshot(root, "before-migrations")
    plan = manage(root, "migrate", "--plan", owner=True)
    write_new(root / "shared/backups/migration-plan.txt", plan)
    print(manage(root, "check", "--deploy", owner=True), flush=True)
    print(
        manage(root, "makemigrations", "--check", "--dry-run", owner=True), flush=True
    )
    print(manage(root, "migrate", "--noinput", owner=True), flush=True)
    prefix = name.replace("-", "_")
    sql(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {prefix}_runtime;\n"
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {prefix}_runtime;\n"
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {prefix}_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {prefix}_runtime;\n"
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {prefix}_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {prefix}_runtime;",
        prefix,
    )
    print(manage(root, "check_rls"), flush=True)
    # Static build uses the unprivileged service account, then becomes read-only.
    shutil.chown(root / "shared/staticfiles", user=name, group=name)
    print(manage(root, "collectstatic", "--noinput"), flush=True)
    for path in [
        root / "shared/staticfiles",
        *(root / "shared/staticfiles").rglob("*"),
    ]:
        shutil.chown(path, user="root", group="root")
        path.chmod(0o755 if path.is_dir() else 0o644)
    print(manage(root, "check_templates"), flush=True)
    snapshot(root, "after-migrations")


def unit(root, name, kind, command, writepaths, extra="", environment_file=True):
    content = f"""[Unit]
Description=Nabio Elege {name} {kind}
After=network.target postgresql.service
StartLimitIntervalSec=120
StartLimitBurst=3
[Service]
Type=simple
User={name}
Group={name}
WorkingDirectory={root}/current
{f"EnvironmentFile={root}/shared/secrets/service.env" if environment_file else ""}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={command}
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
KillSignal=SIGTERM
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={writepaths}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=
LockPersonality=true
RestrictSUIDSGID=true
TasksMax=128
{extra}
[Install]
WantedBy=multi-user.target
"""
    write_new(f"/etc/systemd/system/{name}-{kind}.service", content, 0o644)


def services(root, name, web):
    py = root / "current/.venv/bin"
    writable = f"{root}/shared/media {root}/shared/logs {root}/shared/beat"
    unit(
        root,
        name,
        "redis",
        f"/usr/bin/redis-server {root}/shared/redis.conf",
        f"{root}/shared/redis",
        environment_file=False,
        extra="MemoryMax=256M",
    )
    av_env = f"Environment=LD_LIBRARY_PATH={root}/vendor/usr/lib/x86_64-linux-gnu\nMemoryMax=2G\nCPUQuota=60%"
    unit(
        root,
        name,
        "av",
        f"{root}/vendor/usr/sbin/clamd --config-file={root}/shared/clamd.conf",
        f"{root}/shared/av-data {root}/shared/av-tmp",
        environment_file=False,
        extra=av_env,
    )
    unit(
        root,
        name,
        "freshclam",
        f"{root}/vendor/usr/bin/freshclam --daemon --config-file={root}/shared/freshclam.conf",
        f"{root}/shared/av-data",
        environment_file=False,
        extra=av_env,
    )
    unit(
        root,
        name,
        "web",
        f"{py}/gunicorn nabio_elege.wsgi:application --bind 127.0.0.1:{web} --workers 2 --threads 2 --timeout 30 --graceful-timeout 30 --error-logfile -",
        writable,
        extra="ExecReload=/bin/kill -HUP $MAINPID\nMemoryMax=768M",
    )
    unit(
        root,
        name,
        "worker",
        f"{py}/celery -A nabio_elege worker --loglevel=WARNING --concurrency=1 --hostname={name}@%H",
        writable,
        extra="MemoryMax=512M",
    )
    unit(
        root,
        name,
        "beat",
        f"{py}/celery -A nabio_elege beat --loglevel=WARNING --schedule {root}/shared/beat/schedule",
        writable,
        extra="MemoryMax=256M",
    )
    for kind in ("redis", "av", "freshclam", "web", "worker", "beat"):
        run(["systemd-analyze", "verify", f"/etc/systemd/system/{name}-{kind}.service"])
    run(["systemctl", "daemon-reload"])
    run(
        [
            "systemctl",
            "enable",
            "--now",
            *[
                f"{name}-{k}"
                for k in ("redis", "av", "freshclam", "web", "worker", "beat")
            ],
        ]
    )
    print("EXCLUSIVE_SERVICES_STARTED", flush=True)


def check(root, name):
    print(manage(root, "check_runtime"), flush=True)
    output = run(
        [
            root / "current/.venv/bin/celery",
            "-A",
            "nabio_elege",
            "inspect",
            "ping",
            "--timeout=5",
        ],
        cwd=root / "current",
        env=environment(root),
        user=name,
    )
    if "pong" not in output:
        raise RuntimeError("Worker not responding")
    for kind in ("web", "worker", "beat", "redis", "av", "freshclam"):
        run(["systemctl", "is-active", f"{name}-{kind}"])
    assert_baseline(root)
    print("RUNTIME_AND_WORKER_OK", flush=True)


def main():
    global DIAGNOSTIC_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("init", "antivirus", "migrate", "services", "check", "backup"),
    )
    parser.add_argument("environment", choices=ENVIRONMENTS)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error(
            "Root provisioning and an exact reviewed 40-character Git SHA required"
        )
    name, web, redis_port, av = ENVIRONMENTS[args.environment]
    root = Path("/var/www/apps") / name
    DIAGNOSTIC_ROOT = root
    if root.is_symlink() or root.parent.resolve() != Path("/var/www/apps"):
        raise RuntimeError("Unexpected filesystem target")
    if args.action == "init":
        init(root, name, web, redis_port, av, args.sha, args.environment)
    else:
        state = json.loads((root / "shared/install.json").read_text())
        if state["sha"] != args.sha or (root / "current").resolve().name != args.sha:
            raise RuntimeError("Revision mismatch")
        if args.action == "antivirus":
            antivirus(root, name)
        elif args.action == "migrate":
            migrate(root, name)
        elif args.action == "services":
            services(root, name, web)
        elif args.action == "check":
            check(root, name)
        elif args.action == "backup":
            snapshot(root, "manual")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
