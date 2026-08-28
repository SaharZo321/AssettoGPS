#!/usr/bin/env python3
"""Keep the version string in sync across package.json, pyproject.toml,
manifest.ini, and build_release.ps1's default.

Run this by hand on a branch before opening the release pull request; it
writes the new version everywhere and commits just those four files.

Usage:
    python scripts/bump_version.py 0.1.1[-beta.N]   # write a new version everywhere and commit
    python scripts/bump_version.py 0.1.1 --no-commit  # write the files, leave them unstaged
    python scripts/bump_version.py --check           # verify the files agree
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_JSON = REPO_ROOT / "package.json"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"
MANIFEST_INI = REPO_ROOT / "ac_app" / "lua" / "AssettoGPS" / "manifest.ini"
BUILD_RELEASE_PS1 = REPO_ROOT / "scripts" / "build_release.ps1"

TRACKED_FILES = (PACKAGE_JSON, PYPROJECT_TOML, MANIFEST_INI, BUILD_RELEASE_PS1)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$")

FILE_PATTERNS = {
    PACKAGE_JSON: re.compile(r'"version":\s*"(?P<ver>[^"]+)"'),
    MANIFEST_INI: re.compile(r"VERSION\s*=\s*(?P<ver>\S+)"),
    BUILD_RELEASE_PS1: re.compile(r'\[string\]\$Version\s*=\s*"(?P<ver>[^"]+)"'),
}


def to_pep440(version: str) -> str:
    return re.sub(
        r"-(alpha|beta|rc)\.(\d+)$",
        lambda m: {"alpha": "a", "beta": "b", "rc": "rc"}[m.group(1)] + m.group(2),
        version,
    )


def read_version(path: Path, pattern: re.Pattern) -> str:
    text = path.read_text()
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"Could not find a version in {path}")
    return match.group("ver")


def write_version(path: Path, pattern: re.Pattern, version: str) -> None:
    text = path.read_text()
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one version match in {path}, found {len(matches)}")
    start, end = matches[0].span("ver")
    path.write_text(text[:start] + version + text[end:])


def write_pyproject_version(version: str) -> None:
    pep440 = to_pep440(version)
    text = PYPROJECT_TOML.read_text()
    new_text, count = re.subn(r'(version = ")[^"]+(")', rf"\g<1>{pep440}\g<2>", text, count=1)
    if count != 1:
        raise SystemExit(f"Expected exactly one version match in {PYPROJECT_TOML}, found {count}")
    PYPROJECT_TOML.write_text(new_text)


def read_pyproject_version() -> str:
    text = PYPROJECT_TOML.read_text()
    match = re.search(r'version = "([^"]+)"', text)
    if not match:
        raise SystemExit(f"Could not find a version in {PYPROJECT_TOML}")
    return match.group(1)


def check() -> None:
    package_version = read_version(PACKAGE_JSON, FILE_PATTERNS[PACKAGE_JSON])
    problems = []

    expected_pep440 = to_pep440(package_version)
    actual_pep440 = read_pyproject_version()
    if actual_pep440 != expected_pep440:
        problems.append(
            f"pyproject.toml has {actual_pep440!r}, expected {expected_pep440!r} "
            f"(derived from package.json {package_version!r})"
        )

    for path in (MANIFEST_INI, BUILD_RELEASE_PS1):
        actual = read_version(path, FILE_PATTERNS[path])
        if actual != package_version:
            problems.append(f"{path} has {actual!r}, expected {package_version!r}")

    if problems:
        print("Version mismatch across files:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(1)

    print(f"All files agree on version {package_version!r}")


def commit(version: str) -> None:
    """Commit exactly the four version files, ignoring anything else staged."""
    paths = [str(path.relative_to(REPO_ROOT)) for path in TRACKED_FILES]
    message = f"Bump version to v{version}"
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "commit", "-m", message, "--", *paths],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"git commit failed (rerun with --no-commit to keep the edits):\n"
            f"{result.stdout}{result.stderr}".rstrip()
        )

    print(f"Committed {message!r}")


def bump(version: str, make_commit: bool = True) -> None:
    if not VERSION_RE.match(version):
        raise SystemExit(
            f"Version {version!r} doesn't look like X.Y.Z or X.Y.Z-beta.N / -alpha.N / -rc.N"
        )

    write_version(PACKAGE_JSON, FILE_PATTERNS[PACKAGE_JSON], version)
    write_version(MANIFEST_INI, FILE_PATTERNS[MANIFEST_INI], version)
    write_version(BUILD_RELEASE_PS1, FILE_PATTERNS[BUILD_RELEASE_PS1], version)
    write_pyproject_version(version)

    print(f"Bumped version to {version} (pyproject.toml: {to_pep440(version)})")

    if make_commit:
        commit(version)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("version", nargs="?", help="New version, e.g. 0.1.1 or 0.1.1-beta.2")
    group.add_argument("--check", action="store_true", help="Verify all files agree, don't write")
    parser.add_argument(
        "--no-commit", action="store_true", help="Write the files but don't create a commit"
    )
    args = parser.parse_args(argv)

    if args.check:
        check()
    else:
        bump(args.version, make_commit=not args.no_commit)


if __name__ == "__main__":
    main()
