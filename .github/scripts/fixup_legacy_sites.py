from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Any

from xemu_pgraph_ci_tools.golden_config import GoldenConfig, load_golden_config

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
    except (subprocess.CalledProcessError, OSError) as e:
        logger.warning("Could not fetch remote branches for %s: %s", remote, e)


def load_golden_tests(
    golden_dir: str | None = None, repo_root: str | None = None
) -> set[str]:
    """Loads all known golden test names (formatted as 'Suite:Test') from disk if available."""
    candidates = []
    if golden_dir:
        candidates.append(golden_dir)
    if repo_root:
        candidates.append(
            os.path.join(
                repo_root, "cache", "nxdk_pgraph_tests_golden_results", "results"
            )
        )
    candidates.append(
        os.path.join("cache", "nxdk_pgraph_tests_golden_results", "results")
    )

    for cand in candidates:
        if os.path.isdir(cand):
            png_files = glob.glob("**/*.png", root_dir=cand, recursive=True)
            if png_files:
                goldens = set()
                for f in png_files:
                    if f.endswith("-diff.png"):
                        continue
                    parts = f.replace("\\", "/").split("/")
                    if len(parts) >= 2:
                        suite = parts[-2]
                        test = os.path.splitext(parts[-1])[0]
                        goldens.add(f"{suite}:{test}")
                logger.info("Loaded %d golden tests from %s", len(goldens), cand)
                return goldens

    return set()


def reconstruct_golden_tests_from_tree(compare_base: str) -> set[str]:
    """Attempts to reconstruct the full golden test set from existing valid summaries in the tree."""
    for root, _dirs, files in os.walk(compare_base):
        if "summary.json" in files:
            summary_path = os.path.join(root, "summary.json")
            try:
                with open(summary_path, encoding="utf-8") as f:
                    data = json.load(f)
                no_res = data.get("goldens_without_results", [])
                evaluated = data.get("tests_evaluated", [])
                if len(no_res) > 2000 and len(evaluated) > 3000:
                    combined = set(no_res) | set(evaluated)
                    if len(combined) >= 5000:
                        logger.info(
                            "Reconstructed %d golden tests from %s",
                            len(combined),
                            summary_path,
                        )
                        return combined
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                logger.debug("Failed reading %s", summary_path)
                continue
    return set()


def find_matching_results_dir(
    results_root: str,
    version: str,
    platform: str,
    renderer: str,
) -> str | None:
    """Finds the directory under results_root that matches the given run parameters."""
    if not os.path.isdir(results_root):
        return None

    direct = os.path.join(results_root, version, platform, renderer)
    if os.path.isdir(direct):
        return direct

    if "--" in renderer:
        vendor, glsl = renderer.split("--", 1)
        slash_path = os.path.join(results_root, version, platform, vendor, glsl)
        if os.path.isdir(slash_path):
            return slash_path

    cleaned = renderer.replace("__", "--")
    cleaned_direct = os.path.join(results_root, version, platform, cleaned)
    if os.path.isdir(cleaned_direct):
        return cleaned_direct

    if "--" in cleaned:
        vendor, glsl = cleaned.split("--", 1)
        cleaned_slash = os.path.join(results_root, version, platform, vendor, glsl)
        if os.path.isdir(cleaned_slash):
            return cleaned_slash

    platform_dir = os.path.join(results_root, version, platform)
    if os.path.isdir(platform_dir):
        for entry in os.listdir(platform_dir):
            entry_path = os.path.join(platform_dir, entry)
            if os.path.isdir(entry_path) and (
                renderer.startswith(entry) or cleaned.startswith(entry)
            ):
                return entry_path

    return None


def collect_tests_from_results_dir(results_dir: str) -> set[str]:
    """Discovers all test names from PNG files or results.json within a results directory."""
    tests: set[str] = set()
    if not os.path.isdir(results_dir):
        return tests

    for root, _dirs, files in os.walk(results_dir):
        for f in files:
            if f.endswith(".png") and not f.endswith("-diff.png"):
                suite = os.path.basename(root)
                test = os.path.splitext(f)[0]
                tests.add(f"{suite}:{test}")

    if not tests:
        # Fall back to results.json if no PNGs were found
        for root, _dirs, files in os.walk(results_dir):
            if "results.json" in files:
                results_json_path = os.path.join(root, "results.json")
                try:
                    with open(results_json_path, encoding="utf-8") as rf:
                        data = json.load(rf)
                    for category in ("failed", "flaky", "passed"):
                        items = data.get(category, {})
                        keys = items.keys() if isinstance(items, dict) else items
                        for key in keys:
                            if "::" in key:
                                suite, test = key.split("::", 1)
                                tests.add(f"{suite.replace(' ', '_')}:{test}")
                            elif ":" in key:
                                suite, test = key.split(":", 1)
                                tests.add(f"{suite.replace(' ', '_')}:{test}")
                            else:
                                tests.add(key)
                    for suite_info in data.get("suites", []):
                        s_name = suite_info.get("name", "")
                        for t_info in suite_info.get("tests", []):
                            t_name = t_info.get("name", "")
                            if s_name and t_name:
                                tests.add(f"{s_name}:{t_name}")
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(
                        "Error reading results.json at %s: %s", results_json_path, e
                    )

    return tests


def collect_diff_tests(comp_dir: str) -> set[str]:
    """Finds all test cases that produced a -diff.png file in comp_dir."""
    diff_tests: set[str] = set()
    if not os.path.isdir(comp_dir):
        return diff_tests

    for root, _dirs, files in os.walk(comp_dir):
        for f in files:
            if f.endswith("-diff.png"):
                suite = os.path.basename(root)
                test = f[: -len("-diff.png")]
                diff_tests.add(f"{suite}:{test}")
    return diff_tests


def fixup_comparison_dir(
    comp_dir: str,
    results_root: str,
    golden_tests: set[str],
    *,
    dry_run: bool = False,
    golden_config: GoldenConfig | None = None,
) -> bool:
    """Regenerates summary.json in comp_dir based on actual results and diffs.

    Returns True if summary.json was modified or created, False otherwise.
    """
    comp_dir_abs = os.path.abspath(comp_dir)
    comp_parts = [p for p in comp_dir_abs.replace("\\", "/").split("/") if p]

    # Expected comparison directory structure:
    # ... / <version> / <platform> / <renderer> / <target>
    if len(comp_parts) < 4:
        logger.warning(
            "Cannot determine version/platform/renderer from path: %s", comp_dir
        )
        return False

    _target = comp_parts[-1]
    renderer = comp_parts[-2]
    platform = comp_parts[-3]
    version = comp_parts[-4]

    results_dir = find_matching_results_dir(results_root, version, platform, renderer)
    if not results_dir:
        logger.warning("Could not find matching results dir for %s", comp_dir)

    eval_tests = collect_tests_from_results_dir(results_dir) if results_dir else set()
    diff_tests = collect_diff_tests(comp_dir)

    summary_path = os.path.join(comp_dir, "summary.json")
    old_summary: dict[str, Any] = {}
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                old_summary = json.load(f)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse existing %s: %s", summary_path, e)

    old_eval = old_summary.get("tests_evaluated", [])
    old_diff = old_summary.get("tests_with_differences", {})
    old_nores = old_summary.get("goldens_without_results", [])
    golden_id = old_summary.get("golden_identifier", "Xbox_Hardware")
    result_id = old_summary.get("result_identifier", "")

    all_eval = sorted(eval_tests | diff_tests | set(old_eval))
    new_diff = {
        t: old_diff.get(t, "1")
        for t in sorted(diff_tests | set(old_diff.keys()))
        if t in diff_tests or not diff_tests
    }
    # If diff_tests were found on disk, new_diff is strictly based on tests that have diff files
    if diff_tests:
        new_diff = {t: old_diff.get(t, "1") for t in sorted(diff_tests)}

    new_nogold = sorted(set(all_eval) - set(new_diff.keys()))

    if golden_tests:
        new_nores = sorted(golden_tests - set(all_eval))
    elif old_nores:
        new_nores = sorted(set(old_nores) - set(all_eval))
    else:
        new_nores = []

    if golden_config and golden_config.has_deprecated_tests:
        new_nores = [t for t in new_nores if not golden_config.is_deprecated_fq(t)]

    canonical_golden_id = (golden_id or "Xbox_Hardware").replace("__", "--")
    if not result_id:
        result_id = f"{version}:{platform}:{renderer.replace('--', ':')}"
    canonical_result_id = result_id.replace("__", "--")

    new_summary = {
        "golden_identifier": canonical_golden_id,
        "goldens_without_results": new_nores,
        "result_identifier": canonical_result_id,
        "tests_evaluated": all_eval,
        "tests_with_differences": new_diff,
        "tests_without_goldens": new_nogold,
    }

    if new_summary == old_summary:
        logger.debug("Summary for %s is already up to date.", comp_dir)
        return False

    logger.info(
        "Fixing %s:\n"
        "  eval: %d -> %d\n"
        "  diff: %d -> %d\n"
        "  no_gold: %d -> %d\n"
        "  no_res: %d -> %d",
        summary_path,
        len(old_eval),
        len(all_eval),
        len(old_diff),
        len(new_diff),
        len(old_summary.get("tests_without_goldens", [])),
        len(new_nogold),
        len(old_nores),
        len(new_nores),
    )

    if not dry_run:
        os.makedirs(comp_dir, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as out:
            json.dump(new_summary, out, indent=2, sort_keys=True)
            out.write("\n")

    return True


def discover_comparison_dirs(base_dir: str) -> list[str]:
    """Finds all comparison directories in base_dir."""
    comp_dirs = set()
    if not os.path.isdir(base_dir):
        return []

    for root, _dirs, files in os.walk(base_dir):
        if "summary.json" in files or any(
            root.endswith(target)
            for target in (
                "Xbox--Xbox--DirectX--nv2a",
                "Xbox__Xbox__DirectX__nv2a",
            )
        ):
            comp_dirs.add(root)
    return sorted(comp_dirs)


def fixup_directory(
    compare_base: str,
    results_base: str,
    golden_dir: str | None = None,
    version_filter: str | None = None,
    *,
    dry_run: bool = False,
    golden_config: GoldenConfig | None = None,
) -> int:
    """Finds and fixes all comparison directories under compare_base."""
    golden_tests = load_golden_tests(golden_dir)
    if not golden_tests:
        golden_tests = reconstruct_golden_tests_from_tree(compare_base)

    if golden_config is None:
        golden_config = load_golden_config(golden_dir=golden_dir)

    comp_dirs = discover_comparison_dirs(compare_base)
    modified_count = 0

    for cd in comp_dirs:
        if version_filter and version_filter not in cd:
            continue
        if fixup_comparison_dir(
            cd,
            results_base,
            golden_tests,
            dry_run=dry_run,
            golden_config=golden_config,
        ):
            modified_count += 1

    logger.info("Updated %d comparison summaries in %s", modified_count, compare_base)
    return modified_count


def fixup_archive_branches(
    remote: str = "origin",
    golden_dir: str | None = None,
    version_filter: str | None = None,
    *,
    dry_run: bool = False,
    push: bool = True,
) -> bool:
    """Iterates through remote archive/* branches and fixes up corrupted summaries."""
    repo_root = os.getcwd()
    ensure_remote_fetched(remote, cwd=repo_root)

    branches_output = git("branch", "-r", cwd=repo_root)
    archive_branches = []
    for line in branches_output.splitlines():
        line = line.strip()
        if f"{remote}/archive/" in line and "->" not in line:
            archive_branches.append(line.split(f"{remote}/", 1)[1])

    logger.info("Found %d archive branches to inspect.", len(archive_branches))
    success = True

    for branch in sorted(archive_branches):
        if version_filter and version_filter not in branch:
            continue

        logger.info("Processing archive branch: %s...", branch)
        worktree_dir = os.path.join(repo_root, f".worktree_{branch.replace('/', '_')}")
        try:
            if os.path.exists(worktree_dir):
                shutil.rmtree(worktree_dir, ignore_errors=True)
                git("worktree", "prune", cwd=repo_root)

            git(
                "worktree",
                "add",
                "--detach",
                worktree_dir,
                f"{remote}/{branch}",
                cwd=repo_root,
            )

            comp_dir = os.path.join(worktree_dir, "compare-results")
            results_dir = os.path.join(worktree_dir, "results")
            mod_count = fixup_directory(
                comp_dir,
                results_dir,
                golden_dir=golden_dir,
                dry_run=dry_run,
            )

            if mod_count > 0 and not dry_run:
                git("add", "compare-results", cwd=worktree_dir)
                status = git("status", "--porcelain", cwd=worktree_dir)
                if status:
                    logger.info("Committing updated summaries on %s...", branch)
                    git(
                        "commit",
                        "-m",
                        "Regenerate corrupted summary.json from results and diffs",
                        cwd=worktree_dir,
                    )
                    if push:
                        logger.info("Pushing %s to %s...", branch, remote)
                        git(
                            "push",
                            remote,
                            f"HEAD:refs/heads/{branch}",
                            cwd=worktree_dir,
                        )
        except (subprocess.CalledProcessError, OSError) as e:
            logger.error("Failed to fixup archive branch %s: %s", branch, e)
            success = False
        finally:
            if os.path.exists(worktree_dir):
                try:
                    git(
                        "worktree",
                        "remove",
                        "--force",
                        worktree_dir,
                        cwd=repo_root,
                    )
                except (subprocess.CalledProcessError, OSError):
                    shutil.rmtree(worktree_dir, ignore_errors=True)
                    git("worktree", "prune", cwd=repo_root)

    return success


def fixup_github_pages(
    remote: str = "origin",
    golden_dir: str | None = None,
    version_filter: str | None = None,
    site_output_dir: str | None = None,
    *,
    dry_run: bool = False,
    push: bool = True,
) -> bool:
    """Fixes up corrupted summaries on github_pages and regenerates the results site."""
    repo_root = os.getcwd()
    ensure_remote_fetched(remote, cwd=repo_root)

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
            except (subprocess.CalledProcessError, OSError):
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
        except (subprocess.CalledProcessError, OSError) as e:
            logger.error("Failed to create worktree for github_pages: %s", e)
            return False

    try:
        # Sync latest scripts from repo_root to worktree
        src_scripts = os.path.join(repo_root, ".github", "scripts")
        dst_scripts = os.path.join(worktree_dir, ".github", "scripts")
        if os.path.abspath(src_scripts) != os.path.abspath(
            dst_scripts
        ) and os.path.isdir(src_scripts):
            shutil.copytree(src_scripts, dst_scripts, dirs_exist_ok=True)

        comp_dir = os.path.join(worktree_dir, "compare-results")
        results_dir = os.path.join(worktree_dir, "results")

        mod_count = fixup_directory(
            comp_dir,
            results_dir,
            golden_dir=golden_dir,
            version_filter=version_filter,
            dry_run=dry_run,
        )

        gen_script = os.path.join(
            worktree_dir, ".github", "scripts", "generate_results_site.py"
        )
        if not os.path.isfile(gen_script):
            gen_script = os.path.join(
                repo_root, ".github", "scripts", "generate_results_site.py"
            )

        if os.path.isfile(gen_script) and (mod_count > 0 or site_output_dir):
            logger.info("Regenerating site with generate_results_site.py...")
            site_target = os.path.join(worktree_dir, ".github", "site")
            if os.path.isdir(site_target):
                shutil.rmtree(site_target)
            # Note: pass relative "results" and "compare-results" with cwd=worktree_dir
            # to avoid prepending worktree dir into generated GitHub image URLs.
            subprocess.run(
                [
                    sys.executable,
                    gen_script,
                    "results",
                    site_target,
                    "--comparison-dir",
                    "compare-results",
                    "-v",
                ],
                cwd=worktree_dir,
                check=True,
            )

        if not dry_run:
            git(
                "add",
                "-A",
                "compare-results",
                ".github/scripts",
                ".github/site",
                cwd=worktree_dir,
            )
            status = git("status", "--porcelain", cwd=worktree_dir)
            if status:
                logger.info("Committing updated github_pages...")
                git(
                    "commit",
                    "-m",
                    "Regenerate corrupted summary.json and results site",
                    cwd=worktree_dir,
                )
                if push:
                    logger.info("Pushing github_pages to %s...", remote)
                    git(
                        "push",
                        remote,
                        "HEAD:refs/heads/github_pages",
                        cwd=worktree_dir,
                    )

        if site_output_dir:
            dst_site = os.path.abspath(site_output_dir)
            src_site = os.path.abspath(os.path.join(worktree_dir, ".github", "site"))
            if dst_site != src_site and os.path.isdir(src_site):
                logger.info(
                    "Copying generated site to %s for deployment...",
                    site_output_dir,
                )
                if os.path.exists(dst_site):
                    shutil.rmtree(dst_site)
                os.makedirs(dst_site, exist_ok=True)
                shutil.copytree(src_site, dst_site, dirs_exist_ok=True)

        return True
    finally:
        if worktree_needed and os.path.exists(worktree_dir):
            try:
                git("worktree", "remove", "--force", worktree_dir, cwd=repo_root)
            except (subprocess.CalledProcessError, OSError):
                shutil.rmtree(worktree_dir, ignore_errors=True)
                git("worktree", "prune", cwd=repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fix up corrupted summary.json files in legacy comparison sites."
    )
    parser.add_argument(
        "--target",
        choices=["dir", "github_pages", "archives", "all"],
        default="dir",
        help="Target to fixup: local dir, github_pages branch, archives branches, or all",
    )
    parser.add_argument(
        "--compare-dir",
        default="compare-results",
        help="Path to compare-results directory when target=dir (default: compare-results)",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Path to results directory when target=dir (default: results)",
    )
    parser.add_argument(
        "--golden-dir",
        default=None,
        help="Path to golden results directory",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Optional xemu version or pattern to filter (e.g. xemu-0.8.136)",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote name (default: origin)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate fixup without modifying files or pushing",
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
        fixup_directory(
            args.compare_dir,
            args.results_dir,
            golden_dir=args.golden_dir,
            version_filter=args.version,
            dry_run=args.dry_run,
        )
        return 0

    if args.target == "github_pages":
        success = fixup_github_pages(
            remote=args.remote,
            golden_dir=args.golden_dir,
            version_filter=args.version,
            site_output_dir=args.site_output_dir,
            dry_run=args.dry_run,
            push=should_push,
        )
        return 0 if success else 1

    if args.target == "archives":
        success = fixup_archive_branches(
            remote=args.remote,
            golden_dir=args.golden_dir,
            version_filter=args.version,
            dry_run=args.dry_run,
            push=should_push,
        )
        return 0 if success else 1

    if args.target == "all":
        ok1 = fixup_github_pages(
            remote=args.remote,
            golden_dir=args.golden_dir,
            version_filter=args.version,
            site_output_dir=args.site_output_dir,
            dry_run=args.dry_run,
            push=should_push,
        )
        ok2 = fixup_archive_branches(
            remote=args.remote,
            golden_dir=args.golden_dir,
            version_filter=args.version,
            dry_run=args.dry_run,
            push=should_push,
        )
        return 0 if (ok1 and ok2) else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
