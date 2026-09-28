#!/usr/bin/env python3
# ruff: noqa: BLE001
"""Restores raw test result images for a specific xemu version from git archive branches."""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def git(*args: str, cwd: str | None = None) -> str:
    return subprocess.check_output(["git", *list(args)], cwd=cwd).decode().strip()


def fetch_archive_branches(cwd: str | None = None) -> list[str]:
    """Fetches all archive branches from remote origin."""
    try:
        git(
            "fetch",
            "--force",
            "origin",
            "refs/heads/archive/*:refs/remotes/origin/archive/*",
            cwd=cwd,
        )
    except Exception as e:
        logger.warning("Could not fetch remote archive branches: %s", e)

    branches = git("branch", "-r", cwd=cwd).split()
    return [b.split("origin/")[1] for b in branches if b.startswith("origin/archive/")]


def find_matching_versions(pattern: str, available_branches: list[str]) -> list[str]:
    """Finds version strings from archive branches matching pattern."""
    available_versions = [b.removeprefix("archive/") for b in available_branches]
    if pattern.lower() == "all":
        return sorted(available_versions)

    pattern_escaped = re.escape(pattern).replace(r"\*", ".*")
    regex = re.compile(pattern_escaped, re.IGNORECASE)

    matches = [v for v in available_versions if regex.search(v)]
    return sorted(matches)


def restore_version(
    version: str,
    target_dir: str,
    force: bool = False,
    cwd: str | None = None,
) -> bool:
    """Extracts results for a version from its archive branch into target_dir."""
    branch_ref = f"origin/archive/{version}"
    logger.info("Restoring %s from %s...", version, branch_ref)

    try:
        git("rev-parse", "--verify", branch_ref, cwd=cwd)
    except Exception:
        logger.error("Branch %s not found.", branch_ref)
        return False

    abs_target_dir = os.path.abspath(target_dir)

    try:
        archive_proc = subprocess.Popen(
            ["git", "archive", branch_ref, f"results/{version}"],
            stdout=subprocess.PIPE,
            cwd=cwd,
        )
        tar_proc = subprocess.Popen(
            ["tar", "-x", "-C", abs_target_dir],
            stdin=archive_proc.stdout,
            cwd=cwd,
        )
        if archive_proc.stdout:
            archive_proc.stdout.close()
        tar_proc.communicate()
        if tar_proc.returncode != 0:
            logger.error("Failed to untar results for %s", version)
            return False

        logger.info(
            "Successfully extracted results for %s into %s", version, target_dir
        )

        if force:
            comp_dirs = [
                os.path.join(target_dir, "compare-results", version),
                os.path.join(target_dir, "compare-results", "results", version),
            ]
            for c_dir in comp_dirs:
                if os.path.exists(c_dir):
                    logger.info("Removing comparison cache %s (force requested)", c_dir)
                    shutil.rmtree(c_dir, ignore_errors=True)

        return True

    except Exception:
        logger.exception("Failed to restore version %s", version)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restores archived result images from archive/<version> git branches."
    )
    parser.add_argument(
        "--version",
        help="Target xemu version or pattern (e.g. 0.8.135, xemu-0.8.135-..., or 'all')",
    )
    parser.add_argument(
        "--repo-dir",
        help="Git repository directory containing origin remote (defaults to --target-dir, or current directory, or script root)",
    )
    parser.add_argument(
        "--target-dir",
        default=".",
        help="Directory to extract results into (default: current directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove existing comparison caches for matching versions to force re-running all diffs",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available archived versions and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    repo_dir = args.repo_dir
    if not repo_dir:
        if os.path.isdir(os.path.join(args.target_dir, ".git")):
            repo_dir = args.target_dir
        elif os.path.isdir(".git"):
            repo_dir = "."
        else:
            repo_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )

    available_branches = fetch_archive_branches(cwd=repo_dir)

    if args.list:
        print("Available archived versions:")
        for b in sorted(available_branches):
            print(f"  - {b.removeprefix('archive/')}")
        return 0

    if not args.version:
        parser.error("--version is required when not using --list")

    matching = find_matching_versions(args.version, available_branches)
    if not matching:
        logger.error("No archived version found matching '%s'", args.version)
        print("Available archived versions:")
        for b in sorted(available_branches):
            print(f"  - {b.removeprefix('archive/')}")
        return 1

    os.makedirs(args.target_dir, exist_ok=True)

    success = True
    for v in matching:
        if not restore_version(v, args.target_dir, force=args.force, cwd=repo_dir):
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
