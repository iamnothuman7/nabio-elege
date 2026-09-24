"""Scoped rollout. Application-only unless the named expansion is explicit.

Retains previous code/static assets, backs up first, reloads only Nabio services.
Requires a staging validation marker for the exact production SHA.
The optional registration expansion is hash-pinned and needs a compatible reader
already active. Dependency/settings changes and all other migrations are refused.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.request import Request, urlopen

import first_install as deploy
from operations import backup


def health(root, port):
    request = Request(
        f"http://127.0.0.1:{port}/healthz/",
        headers={"Host": deploy.DOMAIN, "X-Forwarded-Proto": "https"},
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200 or json.load(response) != {"status": "ok"}:
            raise RuntimeError("Unexpected application health")


def switch(root, release):
    link = root / "current.next"
    if link.exists() or link.is_symlink():
        raise RuntimeError("Unfinished release link; inspect before retrying")
    link.symlink_to(release, target_is_directory=True)
    link.replace(root / "current")


def services(root, *, was_active):
    name = root.name
    if was_active:
        deploy.run(["systemctl", "reload", name + "-web"])
        # Celery has no supported in-process code reload; TERM performs a warm stop.
        deploy.run(["systemctl", "restart", name + "-worker", name + "-beat"])
    else:
        deploy.run(
            [
                "systemctl",
                "start",
                *[
                    name + "-" + suffix
                    for suffix in ("redis", "av", "freshclam", "web", "worker", "beat")
                ],
            ]
        )


def rollout(root, sha, port, environment_name, registration_expansion=False):
    deploy.DIAGNOSTIC_ROOT = root
    previous = (root / "current").resolve(strict=True)
    releases = (root / "releases").resolve(strict=True)
    if previous.parent != releases or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise RuntimeError("Invalid scoped release")
    release = releases / sha
    if release.exists():
        raise RuntimeError("Release already exists; refusing mutation")
    if environment_name == "production":
        marker = Path(
            "/var/www/apps/nabio-elege-staging/shared/application-validated.json"
        )
        if not marker.exists() or json.loads(marker.read_text())["sha"] != sha:
            raise RuntimeError("Exact revision has not passed staging validation")
    deploy.assert_baseline(root)
    backup_folder = backup(root)
    deploy.run(["git", "clone", "--no-checkout", deploy.ORIGIN, release])
    deploy.run(["git", "checkout", "--detach", sha], cwd=release)
    if deploy.run(["git", "rev-parse", "HEAD"], cwd=release).strip() != sha:
        raise RuntimeError("Git revision mismatch")
    changes = deploy.run(
        ["git", "diff", "--name-only", previous.name, sha], cwd=release
    ).splitlines()
    if any(
        ("/migrations/" in path and not registration_expansion)
        or path.startswith("nabio_elege/")
        or path.startswith("requirements")
        for path in changes
    ):
        raise RuntimeError(
            "Schema/dependency/settings changes require a separate procedure"
        )
    if registration_expansion:
        from registration_expansion import validate_source

        validate_source(release, previous, changes, deploy.run)
    if (release / "requirements-production.lock").read_bytes() != (
        previous / "requirements-production.lock"
    ).read_bytes():
        raise RuntimeError("Dependency lock mismatch")
    # Identical hash-locked environment, recorded below. No package upgrades.
    (release / ".venv").symlink_to(previous / ".venv", target_is_directory=True)
    (release / ".git").chmod(0o700)
    values = deploy.environment(root)
    values["PYTHONDONTWRITEBYTECODE"] = "1"
    build = root / "shared" / ("static-build-" + sha)
    build.mkdir(mode=0o755)
    shutil.chown(build, user=root.name, group=root.name)
    values["STATIC_ROOT"] = str(build)

    def manage(*args):
        return deploy.run(
            [release / ".venv/bin/python", "manage.py", *args],
            env=values,
            user=root.name,
            cwd=release,
        )

    print(manage("check", "--deploy"), flush=True)
    print(manage("makemigrations", "--check", "--dry-run"), flush=True)
    # Default remains application-only. One explicit, hash-pinned expansion has
    # its own exact-plan, compatible-reader and timeout checks.
    if registration_expansion:
        from registration_expansion import apply

        apply(root, release, values, deploy.run)
    print(manage("migrate", "--check"), flush=True)
    print(manage("check_rls"), flush=True)
    print(manage("check_templates"), flush=True)
    print(manage("collectstatic", "--noinput"), flush=True)
    static = root / "shared/staticfiles"
    old_manifest = (static / "staticfiles.json").read_bytes()
    for path in build.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("Unexpected static symlink")
        relative = path.relative_to(build)
        target = static / relative
        if path.is_dir():
            target.mkdir(exist_ok=True, mode=0o755)
        elif relative.name != "staticfiles.json":
            shutil.copyfile(path, target)
            target.chmod(0o644)
    # Publish the manifest last, atomically. Old hashed assets remain available.
    manifest_next = static / "staticfiles.next.json"
    with manifest_next.open("xb") as output:
        output.write((build / "staticfiles.json").read_bytes())
    manifest_next.chmod(0o644)
    manifest_next.replace(static / "staticfiles.json")
    active = (
        deploy.run(
            ["systemctl", "show", root.name + "-web", "--value", "--property=MainPID"]
        ).strip()
        != "0"
    )
    activated = False
    try:
        switch(root, release)
        activated = True
        services(root, was_active=active)
        for attempt in range(30):
            try:
                health(root, port)
                deploy.check(root, root.name)
                break
            except Exception:
                if attempt == 29:
                    raise
                time.sleep(2)
        deploy.assert_baseline(root)
    except Exception:
        if activated:
            switch(root, previous)
            with manifest_next.open("xb") as output:
                output.write(old_manifest)
            manifest_next.chmod(0o644)
            manifest_next.replace(static / "staticfiles.json")
            services(root, was_active=True)
            health(root, port)
            print("PREVIOUS_RELEASE_RESTORED", previous.name, flush=True)
        raise
    record = {
        "sha": sha,
        "previous_sha": previous.name,
        "venv_source": str((release / ".venv").resolve()),
        "backup": backup_folder.name,
        "utc": deploy.utc(),
        "migrations_applied": registration_expansion,
        "migration": "workspace.0009_simpler_registration"
        if registration_expansion
        else None,
    }
    deploy.write_new(
        root / "shared" / ("rollout-" + deploy.utc() + ".json"), json.dumps(record)
    )
    state_path = root / "shared/install.json"
    state = json.loads(state_path.read_text())
    state.update(sha=sha, previous_sha=previous.name, updated_utc=deploy.utc())
    state_path.write_text(json.dumps(state))
    print("APPLICATION_RELEASE_ACTIVE", sha, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=deploy.ENVIRONMENTS)
    parser.add_argument("--sha", required=True)
    parser.add_argument(
        "--registration-expansion",
        action="store_true",
        help="Apply only the reviewed workspace.0009 additive expansion",
    )
    args = parser.parse_args()
    name, port, _, _ = deploy.ENVIRONMENTS[args.environment]
    root = Path("/var/www/apps") / name
    if (
        os.geteuid() != 0
        or root.is_symlink()
        or root.parent.resolve() != Path("/var/www/apps")
    ):
        raise RuntimeError("Requires scoped management execution")
    with (root / "shared/update-release.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rollout(root, args.sha, port, args.environment, args.registration_expansion)
