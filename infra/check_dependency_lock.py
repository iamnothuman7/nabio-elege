"""Fail CI if the reviewed production pins and wheel-hash lock diverge."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
OPTIONS = {
    "--index-url https://pypi.org/simple",
    "--only-binary=:all:",
    "--require-hashes",
}
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9.+!-]+)(?:\s*;\s*(.+))?$")


def pin(value):
    match = PIN.fullmatch(value.strip())
    if not match:
        raise ValueError("Every dependency must have one exact version")
    name, version, marker = match.groups()
    return re.sub(r"[-_.]+", "-", name).lower(), version, marker or ""


def input_pins(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise ValueError("Recursive requirements include")
    seen.add(path)
    pins = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            included = (path.parent / line[3:]).resolve()
            if included.parent != path.parent:
                raise ValueError(
                    "Requirements include must remain in the same directory"
                )
            pins.update(input_pins(included, seen))
        else:
            pins.add(pin(line))
    return pins


def verify_lock(input_path, lock_path):
    actual, options = set(), set()
    content = lock_path.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--"):
            if line not in OPTIONS:
                raise ValueError("Unapproved index or installation option")
            options.add(line)
            continue
        parts = line.split("--hash=sha256:")
        if len(parts) < 2 or not all(
            re.fullmatch(r"[a-f0-9]{64}", value.strip()) for value in parts[1:]
        ):
            raise ValueError("Missing or invalid wheel hashes")
        dependency = pin(parts[0])
        if dependency in actual:
            raise ValueError("Duplicate locked dependency")
        actual.add(dependency)
    if options != OPTIONS or actual != input_pins(input_path):
        raise ValueError("Production requirements and reviewed hash lock differ")
    return len(actual)


if __name__ == "__main__":
    count = verify_lock(
        ROOT / "requirements-production.txt", ROOT / "requirements-production.lock"
    )
    print(
        f"Production lock verified: {count} pinned dependencies, hashes and binary-only installation required."
    )
