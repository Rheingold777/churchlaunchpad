#!/usr/bin/env python3
"""Build a deterministic public-only Netlify deployment directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def read_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def safe_relative(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Deployment path must stay relative to the repository: {value}")
    return relative


def copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError(f"Deployment package refuses symbolic links: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build_package(root: Path, output: Path, config: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    if output == root or root in output.parents:
        raise ValueError("Deployment output must be outside the repository root.")

    deployment = config.get("deployment", {})
    if deployment.get("provider") != "netlify":
        raise ValueError("Deployment provider must be netlify for this package builder.")
    package = deployment.get("package", {})
    root_patterns = package.get("rootFiles", [])
    directories = package.get("directories", [])
    if not root_patterns:
        raise ValueError("deployment.package.rootFiles must not be empty.")

    selected: dict[str, Path] = {}
    for pattern_value in root_patterns:
        pattern = safe_relative(str(pattern_value)).as_posix()
        matches = sorted(path for path in root.glob(pattern) if path.is_file())
        if not matches:
            raise FileNotFoundError(f"Deployment root-file pattern matched nothing: {pattern}")
        for source in matches:
            relative = source.relative_to(root).as_posix()
            selected[relative] = source

    for directory_value in directories:
        relative_directory = safe_relative(str(directory_value))
        directory = root / relative_directory
        if not directory.is_dir():
            raise FileNotFoundError(f"Deployment directory is missing: {relative_directory.as_posix()}")
        for source in sorted(path for path in directory.rglob("*") if path.is_file()):
            relative = source.relative_to(root).as_posix()
            selected[relative] = source

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    files: list[dict[str, Any]] = []
    total_bytes = 0
    for relative, source in sorted(selected.items()):
        destination = output / Path(relative)
        copy_file(source, destination)
        data = destination.read_bytes()
        total_bytes += len(data)
        files.append(
            {
                "path": relative,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    return {
        "schemaVersion": "1.0",
        "propertyKey": config.get("propertyKey", ""),
        "sourceCommit": os.environ.get("GITHUB_SHA", ""),
        "fileCount": len(files),
        "totalBytes": total_bytes,
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("website-ops.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_config(args.config)
    manifest = build_package(args.root, args.output, config)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "pass",
                "fileCount": manifest["fileCount"],
                "totalBytes": manifest["totalBytes"],
                "output": str(args.output.resolve()),
                "manifest": str(args.manifest.resolve()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
