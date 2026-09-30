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


def ensure_remote_fetched(remote: str = "origin", cwd: str | None = None) -> None:
    """Ensures all remote branches are fetched so origin/* refs are available."""
    try:
        logger.info("Configuring remote %s to fetch all branches...", remote)
        git(
            "config",
            f"remote.{remote}.fetch",
            f"+refs/heads/*:refs/remotes/{remote}/*",
            cwd=cwd,
        )
        git("fetch", remote, "--prune", cwd=cwd)
    except Exception as e:
        logger.warning("Could not fetch remote branches for %s: %s", remote, e)


def resolve_canonical_path(comp_dir: str, base_dir: str) -> str | None:
    """Determines the canonical comparison path for a given directory under base_dir.

    Returns the canonical directory path (using '--'), or None if comp_dir is already canonical.
    """
    rel = os.path.relpath(comp_dir, base_dir)
    parts = [p for p in rel.replace("\\", "/").split("/") if p]

    # Expected structures:
    # 4 parts: [version, platform, gl_vendor--glsl_ver, target]
    # 5 parts: [version, platform, gl_vendor, glsl_ver, target]
    if len(parts) == 4:
        version, platform, gl_combined, target = parts
        canonical_gl = gl_combined.replace("__", "--")
        canonical_target = target.replace("__", "--")
        canonical_rel = os.path.join(version, platform, canonical_gl, canonical_target)
    elif len(parts) == 5:
        version, platform, gl_vendor, glsl_ver, target = parts
        canonical_gl = f"{gl_vendor}--{glsl_ver}".replace("__", "--")
        canonical_target = target.replace("__", "--")
        canonical_rel = os.path.join(version, platform, canonical_gl, canonical_target)
    elif len(parts) == 3:
        version, platform, target = parts
        canonical_target = target.replace("__", "--")
        canonical_rel = os.path.join(version, platform, canonical_target)
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

    # Discover comparison directories: either containing summary.json or ending with Xbox*
    comp_dirs = set()
    summary_files = glob.glob("**/summary.json", root_dir=base_dir, recursive=True)
    for sf in summary_files:
        comp_dirs.add(os.path.dirname(os.path.join(base_dir, sf)))
    for root, dirnames, _ in os.walk(base_dir):
        if any(
            root.endswith(target)
            for target in ("Xbox--Xbox--DirectX--nv2a", "Xbox__Xbox__DirectX__nv2a")
        ):
            comp_dirs.add(root)
            dirnames.clear()

    migrated_count = 0

    for comp_dir in sorted(comp_dirs):
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
                    if not os.path.exists(dest_file) or os.path.getsize(dest_file) == 0:
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        shutil.copy2(src_file, dest_file)

        # 2. Merge summary.json
        src_summary_path = os.path.join(comp_dir, "summary.json")
        dest_summary_path = os.path.join(canonical_dir, "summary.json")
        if os.path.isfile(src_summary_path):
            try:
                src_summary = ComparisonSummary.load_from_file(src_summary_path)
                src_summary.result_identifier = src_summary.result_identifier.replace(
                    "__", "--"
                )
                src_summary.golden_identifier = src_summary.golden_identifier.replace(
                    "__", "--"
                )
                if os.path.isfile(dest_summary_path):
                    try:
                        dest_summary = ComparisonSummary.load_from_file(
                            dest_summary_path
                        )
                        dest_summary.merge(src_summary)
                        dest_summary.result_identifier = (
                            dest_summary.result_identifier.replace("__", "--")
                        )
                        dest_summary.golden_identifier = (
                            dest_summary.golden_identifier.replace("__", "--")
                        )
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
    ensure_remote_fetched(remote)
    branches_output = git("branch", "-r")
    archive_branches = []
    for line in branches_output.splitlines():
        line = line.strip()
        if f"{remote}/archive/" in line and "->" not in line:
            archive_branches.append(line.split(f"{remote}/", 1)[1])

    logger.info("Found %d archive branches to inspect.", len(archive_branches))
    success = True

    for branch in sorted(archive_branches):
        logger.info("Processing archive branch: %s...", branch)
        try:
            # Check if branch has compare-results with '__'
            tree_files = git(
                "ls-tree", "-r", "--name-only", f"{remote}/{branch}"
            ).splitlines()
            legacy_entries = [
                f
                for f in tree_files
                if f.startswith("compare-results/") and ("__" in f)
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
            if os.path.exists(worktree_dir):
                try:
                    git("worktree", "remove", "--force", worktree_dir)
                except Exception:
                    shutil.rmtree(worktree_dir, ignore_errors=True)
                    git("worktree", "prune")

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
                            "Clean up legacy comparison paths using '__' to '--'",
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
                if os.path.exists(worktree_dir):
                    try:
                        git("worktree", "remove", "--force", worktree_dir)
                    except Exception:
                        shutil.rmtree(worktree_dir, ignore_errors=True)
                        git("worktree", "prune")

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
    site_output_dir: str | None = None,
) -> bool:
    """Cleans up compare-results on github_pages, removes old site compare pages with '--',

    regenerates .github/site, and commits/pushes.
    """
    ensure_remote_fetched(remote, cwd=repo_root)
    logger.info("Cleaning up github_pages branch...")

    try:
        tree_files = git(
            "ls-tree", "-r", "--name-only", f"{remote}/github_pages", cwd=repo_root
        ).splitlines()
        legacy_entries = [
            f for f in tree_files if f.startswith("compare-results/") and ("__" in f)
        ]
        logger.info(
            "Found %d legacy compare files on %s/github_pages.",
            len(legacy_entries),
            remote,
        )
    except Exception as e:
        logger.warning("Could not list tree for %s/github_pages: %s", remote, e)
        legacy_entries = []

    if dry_run:
        logger.info(
            "[Dry Run] Would clean up %d legacy compare files on github_pages.",
            len(legacy_entries),
        )
        return True

    worktree_needed = not os.path.isdir(os.path.join(repo_root, "compare-results"))
    worktree_dir = (
        os.path.join(repo_root, ".worktree_github_pages")
        if worktree_needed
        else repo_root
    )

    if worktree_needed:
        logger.info("Creating worktree for %s/github_pages...", remote)
        if os.path.exists(worktree_dir):
            try:
                git("worktree", "remove", "--force", worktree_dir, cwd=repo_root)
            except Exception:
                shutil.rmtree(worktree_dir, ignore_errors=True)
                git("worktree", "prune", cwd=repo_root)
        try:
            git(
                "worktree",
                "add",
                "--detach",
                worktree_dir,
                f"{remote}/github_pages",
                cwd=repo_root,
            )
        except Exception as e:
            logger.error("Failed to create worktree for github_pages: %s", e)
            return False

    try:
        src_scripts = os.path.join(repo_root, ".github", "scripts")
        dst_scripts = os.path.join(worktree_dir, ".github", "scripts")
        if os.path.abspath(src_scripts) != os.path.abspath(
            dst_scripts
        ) and os.path.isdir(src_scripts):
            logger.info("Syncing updated .github/scripts to github_pages...")
            shutil.copytree(src_scripts, dst_scripts, dirs_exist_ok=True)

        comp_dir = os.path.join(worktree_dir, "compare-results")
        cleanup_directory(comp_dir, dry_run=False)

        # Clean up any legacy directories in .github/site/compare if present
        site_compare_dir = os.path.join(worktree_dir, ".github", "site", "compare")
        if os.path.isdir(site_compare_dir):
            for entry in os.listdir(site_compare_dir):
                entry_path = os.path.join(site_compare_dir, entry)
                if os.path.isdir(entry_path):
                    for root, dirnames, _filenames in os.walk(
                        entry_path, topdown=False
                    ):
                        for d in dirnames:
                            if "__" in d:
                                legacy_p = os.path.join(root, d)
                                logger.info(
                                    "Removing legacy site directory: %s", legacy_p
                                )
                                shutil.rmtree(legacy_p, ignore_errors=True)

        gen_script = os.path.join(
            worktree_dir, ".github", "scripts", "generate_results_site.py"
        )
        if not os.path.isfile(gen_script):
            gen_script = os.path.join(
                repo_root, ".github", "scripts", "generate_results_site.py"
            )

        if os.path.isfile(gen_script):
            logger.info("Regenerating site with generate_results_site.py...")
            site_target = os.path.join(worktree_dir, ".github", "site")
            subprocess.run(
                [
                    sys.executable,
                    gen_script,
                    os.path.join(worktree_dir, "results"),
                    site_target,
                    "--comparison-dir",
                    comp_dir,
                    "-v",
                ],
                check=True,
            )

        git(
            "add",
            "-A",
            "compare-results",
            ".github/scripts",
            ".github/site",
            cwd=worktree_dir,
        )
        status = git("status", "--porcelain", cwd=worktree_dir)
        if status and push:
            logger.info("Committing and pushing cleaned github_pages...")
            git(
                "commit",
                "-m",
                "Clean up legacy comparison paths using '__' to '--'",
                cwd=worktree_dir,
            )
            git("push", remote, "HEAD:refs/heads/github_pages", cwd=worktree_dir)

        if site_output_dir:
            dst_site = os.path.abspath(site_output_dir)
            src_site = os.path.abspath(os.path.join(worktree_dir, ".github", "site"))
            if dst_site != src_site and os.path.isdir(src_site):
                logger.info(
                    "Copying generated site to %s for deployment...", site_output_dir
                )
                os.makedirs(dst_site, exist_ok=True)
                shutil.copytree(src_site, dst_site, dirs_exist_ok=True)

        return True
    finally:
        if worktree_needed and os.path.exists(worktree_dir):
            try:
                git("worktree", "remove", "--force", worktree_dir, cwd=repo_root)
            except Exception:
                shutil.rmtree(worktree_dir, ignore_errors=True)
                git("worktree", "prune", cwd=repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean up paths using '__' to canonical '--'"
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
        "--site-output-dir",
        default=None,
        help="Optional directory to copy generated .github/site to for GitHub Pages deployment",
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
            remote=args.remote,
            dry_run=args.dry_run,
            push=should_push,
            site_output_dir=args.site_output_dir,
        )
        return 0 if success else 1

    if args.target == "archives":
        success = cleanup_archive_branches(
            remote=args.remote, dry_run=args.dry_run, push=should_push
        )
        return 0 if success else 1

    if args.target == "all":
        ok1 = cleanup_github_pages(
            remote=args.remote,
            dry_run=args.dry_run,
            push=should_push,
            site_output_dir=args.site_output_dir,
        )
        ok2 = cleanup_archive_branches(
            remote=args.remote, dry_run=args.dry_run, push=should_push
        )
        return 0 if (ok1 and ok2) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
