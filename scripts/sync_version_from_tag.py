#!/usr/bin/env python3
"""Sync project version files from a GitHub release/tag value."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"[^"]+"\s*$')
FASTAPI_VERSION_RE = re.compile(r'(FastAPI\([^)]*?\bversion=")([^"]+)(")', re.DOTALL)


def normalize_tag(tag: str) -> str:
    version = tag.strip()
    if version.startswith("refs/tags/"):
        version = version[len("refs/tags/") :]
    if version.startswith("v"):
        version = version[1:]
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(
            f"Invalid release tag '{tag}'. Expected format 'vX.Y.Z' or 'X.Y.Z'."
        )
    return version


def update_frontend_package(frontend_package_path: Path, version: str) -> bool:
    data = json.loads(frontend_package_path.read_text(encoding="utf-8"))
    current = data.get("version")
    if not isinstance(current, str):
        raise RuntimeError(f"Missing string 'version' in {frontend_package_path}")
    changed = current != version
    data["version"] = version
    if changed:
        frontend_package_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    return changed


def update_pyproject(pyproject_path: Path, version: str) -> bool:
    contents = pyproject_path.read_text(encoding="utf-8")
    replaced, count = PYPROJECT_VERSION_RE.subn(f'version = "{version}"', contents, count=1)
    if count != 1:
        raise RuntimeError(
            f"Expected to update exactly one project version line in {pyproject_path}, got {count}."
        )
    changed = replaced != contents
    if changed:
        pyproject_path.write_text(replaced, encoding="utf-8")
    return changed


def update_backend_fastapi(main_path: Path, version: str) -> bool:
    contents = main_path.read_text(encoding="utf-8")
    replaced, count = FASTAPI_VERSION_RE.subn(rf'\g<1>{version}\g<3>', contents, count=1)
    if count != 1:
        raise RuntimeError(
            f"Expected to update exactly one FastAPI version field in {main_path}, got {count}."
        )
    changed = replaced != contents
    if changed:
        main_path.write_text(replaced, encoding="utf-8")
    return changed


def verify_versions(frontend_package_path: Path, pyproject_path: Path, main_path: Path, expected: str) -> None:
    package_data = json.loads(frontend_package_path.read_text(encoding="utf-8"))
    frontend_version = package_data.get("version")
    if frontend_version != expected:
        raise RuntimeError(
            f"Frontend version mismatch in {frontend_package_path}: {frontend_version!r} != {expected!r}"
        )

    pyproject_contents = pyproject_path.read_text(encoding="utf-8")
    pyproject_match = PYPROJECT_VERSION_RE.search(pyproject_contents)
    if not pyproject_match:
        raise RuntimeError(f"Could not read project version from {pyproject_path}")
    pyproject_version = pyproject_match.group(0).split("=", 1)[1].strip().strip('"')
    if pyproject_version != expected:
        raise RuntimeError(
            f"Backend package version mismatch in {pyproject_path}: {pyproject_version!r} != {expected!r}"
        )

    main_contents = main_path.read_text(encoding="utf-8")
    main_match = FASTAPI_VERSION_RE.search(main_contents)
    if not main_match:
        raise RuntimeError(f"Could not read FastAPI version from {main_path}")
    backend_runtime_version = main_match.group(2)
    if backend_runtime_version != expected:
        raise RuntimeError(
            f"Backend runtime version mismatch in {main_path}: {backend_runtime_version!r} != {expected!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default="",
        help="Release tag to sync from (e.g. v0.0.2 or refs/tags/v0.0.2).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the target version without writing files.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print normalized version and exit.",
    )
    args = parser.parse_args()

    tag = args.tag.strip()
    if not tag:
        raise SystemExit("--tag is required")

    version = normalize_tag(tag)
    if args.print_only:
        print(version)
        return 0

    repo_root = Path(__file__).resolve().parents[1]
    frontend_package_path = repo_root / "frontend" / "package.json"
    pyproject_path = repo_root / "backend" / "pyproject.toml"
    main_path = repo_root / "backend" / "app" / "main.py"

    if args.dry_run:
        print(f"dry-run ok: target version {version}")
        return 0

    changed = []
    if update_frontend_package(frontend_package_path, version):
        changed.append(str(frontend_package_path.relative_to(repo_root)))
    if update_pyproject(pyproject_path, version):
        changed.append(str(pyproject_path.relative_to(repo_root)))
    if update_backend_fastapi(main_path, version):
        changed.append(str(main_path.relative_to(repo_root)))

    verify_versions(frontend_package_path, pyproject_path, main_path, version)

    print(f"version={version}")
    if changed:
        print("changed_files=" + ",".join(changed))
    else:
        print("changed_files=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
