#!/usr/bin/env python
"""Zip a package directory, skipping anything matched by a gitignore-style
ignore file.

Rules are merged in this order (later rules win, as in .gitignore):
  1. base:    .zipignore next to this script (or --ignore-file)
  2. package: <package-dir>/.zipignore, if present

Patterns are matched relative to the package directory, with full .gitignore
semantics: `__pycache__/` matches at any depth, `/build/` only at the top,
`!keep.me` re-includes, etc.

Usage:
    python scripts/zip/zip.py <package-dir> [--out PATH] [--ignore-file PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

import pathspec


def load_spec(ignore_files: list[Path]) -> pathspec.GitIgnoreSpec:
    lines: list[str] = []
    for f in ignore_files:
        if f.is_file():
            lines += f.read_text().splitlines()
    return pathspec.GitIgnoreSpec.from_lines(lines)


def collect(pkg: Path, spec: pathspec.GitIgnoreSpec, skip: Path | None) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(pkg):
        rel_root = Path(root).relative_to(pkg)
        # Prune excluded directories so we never descend into them.
        dirs[:] = sorted(
            d for d in dirs if not spec.match_file(f"{(rel_root / d).as_posix()}/")
        )
        for n in sorted(names):
            rel = rel_root / n
            full = pkg / rel
            if spec.match_file(rel.as_posix()):
                continue
            if skip is not None and full.resolve() == skip:
                continue  # never zip the archive into itself
            files.append(rel)
    return files


def main() -> int:
    root = Path(os.environ.get("PIXI_PROJECT_ROOT", Path.cwd()))

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0]) #type: ignore
    ap.add_argument("package", type=Path, help="package directory to archive")
    ap.add_argument("--out", type=Path, help="output zip (default: dist/<name>.zip)")
    ap.add_argument(
        "--ignore-file", type=Path, default=Path(__file__).resolve().parent / ".zipignore",
        help="base gitignore-style exclusions (default: .zipignore beside this script)",
    )
    ap.add_argument("--dry-run", action="store_true", help="list files, write nothing")
    a = ap.parse_args()

    pkg = a.package.resolve()
    if not pkg.is_dir():
        print(f"error: '{a.package}' is not a directory", file=sys.stderr)
        return 1

    out = (a.out or root / "dist" / f"{pkg.name}.zip").resolve()
    # Base rules first, then the package's own; later rules take precedence.
    spec = load_spec([a.ignore_file, pkg / ".zipignore"])
    files = collect(pkg, spec, skip=out)

    if a.dry_run:
        for f in files:
            print(f"{pkg.name}/{f.as_posix()}")
        print(f"\n{len(files)} files would be archived", file=sys.stderr)
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    # Mode "w" always writes a fresh archive (no stale entries from earlier runs).
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in files:
            zf.write(pkg / f, arcname=f"{pkg.name}/{f.as_posix()}")

    print(f"📦 {pkg.name}: {len(files)} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())