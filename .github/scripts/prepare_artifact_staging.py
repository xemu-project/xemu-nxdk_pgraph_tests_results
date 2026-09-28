#!/usr/bin/env python3

# ruff: noqa: BLE001 Do not catch blind exception
"""Stages modified and added files, and records deleted files for artifact upload."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def git(*args: str, cwd: str | None = None) -> str:
    return subprocess.check_output(["git", *list(args)], cwd=cwd).decode().strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stages modified/added files and records deleted files into a staging directory."
    )
    parser.add_argument(
        "--source-dir",
        default=".",
        help="Source directory (repository working tree)",
    )
    parser.add_argument(
        "--staging-dir",
        default="../artifact-staging",
        help="Destination directory for staged files",
    )

    args = parser.parse_args()
    source_dir = os.path.abspath(args.source_dir)
    staging_dir = os.path.abspath(args.staging_dir)

    os.makedirs(staging_dir, exist_ok=True)

    try:
        # Clean up legacy compare-results/results directory if it exists
        legacy_dir = os.path.join(source_dir, "compare-results", "results")
        if os.path.isdir(legacy_dir):
            print("Cleaning up legacy compare-results/results directory...")
            subprocess.run(
                ["git", "rm", "-r", "--cached", "compare-results/results"],
                cwd=source_dir,
                check=False,
            )
            shutil.rmtree(legacy_dir, ignore_errors=True)

        # Add target directories to git index so untracked and modified files are indexed
        for d in [".github/scripts", "dev_scripts", "results", "compare-results"]:
            full_d = os.path.join(source_dir, d)
            if os.path.exists(full_d):
                subprocess.run(["git", "add", d], cwd=source_dir, check=False)

        diff_out = git("diff", "--name-only", "--cached", cwd=source_dir)
    except Exception as e:
        print(f"Error checking git diff: {e}", file=sys.stderr)
        return 1

    if not diff_out.strip():
        print("No changes detected.")
        with open(
            os.path.join(staging_dir, "KEEP_ARTIFACT"), "w", encoding="utf-8"
        ) as f:
            f.write("")
        return 0

    all_changed = [line.strip() for line in diff_out.splitlines() if line.strip()]
    deleted_files: list[str] = []
    staged_count = 0

    for rel_path in all_changed:
        src_file = os.path.join(source_dir, rel_path)
        if os.path.isfile(src_file):
            dst_file = os.path.join(staging_dir, rel_path)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
            staged_count += 1
        elif not os.path.exists(src_file):
            deleted_files.append(rel_path)

    if deleted_files:
        with open(
            os.path.join(staging_dir, ".deleted_files.txt"), "w", encoding="utf-8"
        ) as f:
            f.write("\n".join(deleted_files) + "\n")
        print(f"Recorded {len(deleted_files)} deleted file(s).")

    if staged_count == 0 and not deleted_files:
        with open(
            os.path.join(staging_dir, "KEEP_ARTIFACT"), "w", encoding="utf-8"
        ) as f:
            f.write("")
        print("No file changes to copy. Created KEEP_ARTIFACT.")
    else:
        print(f"Successfully staged {staged_count} file(s) into {staging_dir}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
