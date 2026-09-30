#!/usr/bin/env python3

# ruff: noqa: BLE001

from __future__ import annotations

import argparse
import glob
import logging
import os
import shutil
import subprocess
import sys

from xemu_pgraph_ci_tools.models import ComparisonSummary

logger = logging.getLogger(__name__)


def git(*args: str, cwd: str | None = None) -> str:
    """Executes a git command and returns stripped stdout."""
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def resolve_canonical_path(comp_dir: str, base_dir: str) -> str | None:
    """Determines the canonical comparison path for a given directory under base_dir.

    Returns the canonical directory path, or None if comp_dir is already canonical.
    """
    rel = os.path.relpath(comp_dir, base_dir)
    parts = [p for p in rel.replace("\\", "/").split("/") if p]

    # Expected structures:
    # 4 parts: [version, platform, gl_info--glsl_info, target]
    # 5 parts: [version, platform, gl_info, glsl_info, target]
    if len(parts) == 4:
        version, platform, gl_combined, target = parts
        if "--" in gl_combined:
            gl_parts = gl_combined.split("--", 1)
            gl_vendor = gl_parts[0]
            glsl_ver = gl_parts[1]
        elif "__" in gl_combined:
            gl_parts = gl_combined.split("__", 1)
            gl_vendor = gl_parts[0]
            glsl_ver = gl_parts[1]
        else:
            gl_vendor = gl_combined
            glsl_ver = ""

        canonical_target = target.replace("--", "__")
        if glsl_ver:
            canonical_rel = os.path.join(
                version, platform, gl_vendor, glsl_ver, canonical_target
            )
        else:
            canonical_rel = os.path.join(version, platform, gl_vendor, canonical_target)
    elif len(parts) == 5:
        version, platform, gl_vendor, glsl_ver, target = parts
        canonical_target = target.replace("--", "__")
        canonical_rel = os.path.join(
            version, platform, gl_vendor, glsl_ver, canonical_target
        )
    else:
        return None

    canonical_full = os.path.join(base_dir, canonical_rel)
    if os.path.abspath(comp_dir) == os.path.abspath(canonical_full):
        return None

    return canonical_full


def cleanup_directory(base_dir: str, *, dry_run: bool = False) -> int:
    """Finds all legacy comparison directories under base_dir, migrates their files

    and merged summaries to canonical directories, and removes legacy directories.
    Returns the number of migrated directories.
    """
    if not os.path.isdir(base_dir):
        logger.info("Base directory '%s' does not exist.", base_dir)
        return 0

    # Discover directories containing summary.json
    summary_files = glob.glob("**/summary.json", root_dir=base_dir, recursive=True)
    migrated_count = 0

    for sf in sorted(summary_files):
        comp_dir = os.path.dirname(os.path.join(base_dir, sf))
        canonical_dir = resolve_canonical_path(comp_dir, base_dir)
        if not canonical_dir:
            continue

        migrated_count += 1
        logger.info("[Migrate] %s -> %s", comp_dir, canonical_dir)
        if dry_run:
            continue

        os.makedirs(canonical_dir, exist_ok=True)

        # 1. Migrate diff PNGs
        for root, _dirnames, filenames in os.walk(comp_dir):
            for filename in filenames:
                if filename.endswith(".png"):
                    src_file = os.path.join(root, filename)
                    rel_file = os.path.relpath(src_file, comp_dir)
                    dest_file = os.path.join(canonical_dir, rel_file)
                    if not os.path.exists(dest_file):
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        shutil.copy2(src_file, dest_file)

        # 2. Merge summary.json
        src_summary_path = os.path.join(comp_dir, "summary.json")
        dest_summary_path = os.path.join(canonical_dir, "summary.json")
        if os.path.isfile(src_summary_path):
            try:
                src_summary = ComparisonSummary.load_from_file(src_summary_path)
                if os.path.isfile(dest_summary_path):
                    try:
                        dest_summary = ComparisonSummary.load_from_file(
                            dest_summary_path
                        )
                        dest_summary.merge(src_summary)
                        dest_summary.save_to_file(dest_summary_path)
                    except Exception:
                        src_summary.save_to_file(dest_summary_path)
                else:
                    src_summary.save_to_file(dest_summary_path)
            except Exception as e:
                logger.warning(
                    "Could not merge summary from %s: %s", src_summary_path, e
                )

        # 3. Remove legacy directory
        shutil.rmtree(comp_dir, ignore_errors=True)

        # 4. Clean up any now-empty parent directories
        parent = os.path.dirname(comp_dir)
        while parent and os.path.abspath(parent) != os.path.abspath(base_dir):
            try:
                if not os.listdir(parent):
                    os.rmdir(parent)
                    parent = os.path.dirname(parent)
                else:
                    break
            except OSError:
                break

    logger.info("Cleaned %d legacy director(y/ies) in %s", migrated_count, base_dir)
    return migrated_count


def cleanup_archive_branches(
    remote: str = "origin",
    *,
    dry_run: bool = False,
    push: bool = True,
) -> bool:
    """Iterates through all remote archive/* branches, migrates legacy paths in compare-results/,

    commits and pushes the updated branch trees.
    """
    branches_output = git("branch", "-r")
    archive_branches = [
        b.strip().split(f"{remote}/")[1]
        for b in branches_output.split()
        if f"{remote}/archive/" in b
    ]

    logger.info("Found %d archive branches to inspect.", len(archive_branches))
    success = True

    for branch in sorted(archive_branches):
        logger.info("Processing archive branch: %s...", branch)
        try:
            # Check if branch has compare-results with '--'
            tree_files = git(
                "ls-tree", "-r", "--name-only", f"{remote}/{branch}"
            ).splitlines()
            legacy_entries = [
                f
                for f in tree_files
                if f.startswith("compare-results/") and ("--" in f)
            ]
            if not legacy_entries:
                logger.info("  [OK] %s has no legacy paths.", branch)
                continue

            logger.info(
                "  [!] %s has %d legacy compare files. Checking out to clean...",
                branch,
                len(legacy_entries),
            )
            if dry_run:
                continue

            # Create a detached worktree or checkout branch
            worktree_dir = f".worktree_{branch.replace('/', '_')}"
            try:
                git("worktree", "add", "--detach", worktree_dir, f"{remote}/{branch}")
                comp_dir = os.path.join(worktree_dir, "compare-results")
                migrated = cleanup_directory(comp_dir, dry_run=False)
                if migrated > 0:
                    git("add", "-A", "compare-results", cwd=worktree_dir)
                    status = git("status", "--porcelain", cwd=worktree_dir)
                    if status:
                        git(
                            "commit",
                            "-m",
                            "Clean up legacy comparison paths using '--' to '__'",
                            cwd=worktree_dir,
                        )
                        if push:
                            logger.info(
                                "  [Push] Pushing cleaned %s to %s...", branch, remote
                            )
                            git(
                                "push",
                                remote,
                                f"HEAD:refs/heads/{branch}",
                                cwd=worktree_dir,
                            )
            finally:
                git("worktree", "remove", "--force", worktree_dir)

        except Exception:
            logger.exception("Failed processing branch %s", branch)
            success = False

    return success


def cleanup_github_pages(
    remote: str = "origin",
    *,
    dry_run: bool = False,
    push: bool = True,
    repo_root: str = ".",
) -> bool:
    """Cleans up compare-results on github_pages, removes old site compare pages with '--',

    regenerates .github/site, and commits/pushes.
    """
    logger.info("Cleaning up github_pages branch...")
    comp_dir = os.path.join(repo_root, "compare-results")
    migrated = cleanup_directory(comp_dir, dry_run=dry_run)

    # Also clean up any legacy directories in .github/site/compare if present
    site_compare_dir = os.path.join(repo_root, ".github", "site", "compare")
    if os.path.isdir(site_compare_dir):
        for entry in os.listdir(site_compare_dir):
            entry_path = os.path.join(site_compare_dir, entry)
            if os.path.isdir(entry_path):
                for root, dirnames, _filenames in os.walk(entry_path, topdown=False):
                    for d in dirnames:
                        if "--" in d:
                            legacy_p = os.path.join(root, d)
                            logger.info("Removing legacy site directory: %s", legacy_p)
                            if not dry_run:
                                shutil.rmtree(legacy_p, ignore_errors=True)

    if dry_run:
        logger.info("[Dry Run] Would commit and push cleaned github_pages.")
        return True

    if migrated > 0:
        logger.info("Regenerating site with generate_results_site.py...")
        gen_script = os.path.join(
            repo_root, ".github", "scripts", "generate_results_site.py"
        )
        if os.path.isfile(gen_script):
            subprocess.run(
                [
                    sys.executable,
                    gen_script,
                    os.path.join(repo_root, "results"),
                    os.path.join(repo_root, ".github", "site"),
                    "--comparison-dir",
                    comp_dir,
                    "-v",
                ],
                check=True,
            )

        git("add", "-A", "compare-results", ".github/site", cwd=repo_root)
        status = git("status", "--porcelain", cwd=repo_root)
        if status and push:
            git(
                "commit",
                "-m",
                "Clean up legacy comparison paths using '--' to '__'",
                cwd=repo_root,
            )
            git("push", remote, "HEAD:refs/heads/github_pages", cwd=repo_root)

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean up legacy paths using '--' to canonical '__'"
    )
    parser.add_argument(
        "--target",
        choices=["dir", "github_pages", "archives", "all"],
        default="dir",
        help="Target to clean up: local dir, github_pages branch, archives branches, or all",
    )
    parser.add_argument(
        "--compare-dir",
        default="compare-results",
        help="Path to compare-results directory when target=dir",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote name (default: origin)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate cleanup without modifying or pushing files",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit changes but do not push to remote",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    should_push = not args.no_push and not args.dry_run

    if args.target == "dir":
        cleanup_directory(args.compare_dir, dry_run=args.dry_run)
        return 0

    if args.target == "github_pages":
        success = cleanup_github_pages(
            remote=args.remote, dry_run=args.dry_run, push=should_push
        )
        return 0 if success else 1

    if args.target == "archives":
        success = cleanup_archive_branches(
            remote=args.remote, dry_run=args.dry_run, push=should_push
        )
        return 0 if success else 1

    if args.target == "all":
        ok1 = cleanup_github_pages(
            remote=args.remote, dry_run=args.dry_run, push=should_push
        )
        ok2 = cleanup_archive_branches(
            remote=args.remote, dry_run=args.dry_run, push=should_push
        )
        return 0 if (ok1 and ok2) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
