#!/usr/bin/env python3
# ruff: noqa: BLE001
"""Restores raw test result images from git archive branches based on a result page URL."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Known platform prefixes and architecture names to help disambiguate path tokens
KNOWN_PLATFORM_PREFIXES = (
    "darwin",
    "linux",
    "windows",
    "win32",
    "win64",
    "macos",
    "osx",
)
KNOWN_GOLDEN_NAMES = ("xbox_hardware", "golden", "hardware")


@dataclass
class ResultTarget:
    """Target test result identified from URL or path."""

    version: str
    platform: str | None = None
    renderer: str | None = None
    suite: str | None = None
    raw_url: str = ""


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


def parse_result_url(url: str) -> ResultTarget:
    """Parses a site page URL or relative path into a ResultTarget.

    Supported URL patterns:
      - https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/<version>/<platform>/<renderer>/index.html
      - https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/<version>/<platform>/<renderer>/<suite>/index.html
      - https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/<version>/<platform>/<vendor>/<glsl>/index.html
      - results/<version>/<platform>/<renderer>/index.html
      - <version>/<platform>/<renderer>
      - <version>
    """
    raw_url = url.strip()
    parsed = urlparse(raw_url)
    raw_path = parsed.path if parsed.path else raw_url
    raw_path = unquote(raw_path.split("?")[0].split("#")[0]).strip()

    # Split into path components, removing empty elements
    parts = [p for p in raw_path.replace("\\", "/").split("/") if p]

    # Strip repo name prefix if present
    if parts and parts[0] == "xemu-nxdk_pgraph_tests_results":
        parts = parts[1:]

    # Locate 'results' or 'compare' root markers if present
    after_root: list[str] = []
    is_compare = False
    for i, part in enumerate(parts):
        if part in ("results", "compare"):
            after_root = parts[i + 1 :]
            is_compare = part == "compare"
            break

    if not after_root:
        after_root = parts

    if not after_root:
        raise ValueError(f"Unable to parse result information from URL/path: {url}")

    platform: str | None = None
    renderer: str | None = None
    suite: str | None = None

    # Check for colon-separated composite identifiers, e.g. <version>:<platform>:<vendor>:<glsl>
    first_part = after_root[0]
    if ":" in first_part:
        colon_parts = first_part.split(":")
        version = colon_parts[0]
        platform = colon_parts[1] if len(colon_parts) > 1 else None
        renderer = "--".join(colon_parts[2:]) if len(colon_parts) > 2 else None
        return ResultTarget(
            version=version,
            platform=platform,
            renderer=renderer,
            suite=None,
            raw_url=raw_url,
        )

    version = after_root[0]
    remaining = after_root[1:]

    # Filter out html/json/png filenames
    cleaned_remaining: list[str] = []
    for seg in remaining:
        if seg.endswith((".html", ".htm", ".json", ".png")):
            # If it's a specific suite page (e.g. 2D_Lines.html), note suite name
            stem = seg.rsplit(".", 1)[0]
            if stem != "index":
                cleaned_remaining.append(stem)
            continue
        cleaned_remaining.append(seg)

    renderer_parts: list[str] = []

    for seg in cleaned_remaining:
        seg_lower = seg.lower()

        # Ignore golden hardware names in compare URLs
        if is_compare and seg_lower in KNOWN_GOLDEN_NAMES:
            continue

        # Check for platform identifier (e.g. Darwin_arm64, Linux_x86_64, Windows_AMD64)
        if platform is None and any(
            seg_lower.startswith(pfx) for pfx in KNOWN_PLATFORM_PREFIXES
        ):
            platform = seg
            continue

        # Check for renderer identifier (e.g. gl_..., vk_..., gslv_...)
        if seg.startswith(("gl_", "vk_", "gslv_")) or "--" in seg:
            renderer_parts.append(seg)
            continue

        # If we already have platform and renderer, subsequent tokens may be suite name
        if platform and renderer_parts:
            suite = seg
        elif platform is None and not renderer_parts:
            # Fallback if platform name doesn't match known prefixes
            platform = seg
        else:
            renderer_parts.append(seg)

    if renderer_parts:
        renderer = "--".join(renderer_parts).replace("__", "--")

    return ResultTarget(
        version=version,
        platform=platform,
        renderer=renderer,
        suite=suite,
        raw_url=raw_url,
    )


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

    try:
        branches = git("branch", "-r", cwd=cwd).split()
        return [
            b.split("origin/")[1] for b in branches if b.startswith("origin/archive/")
        ]
    except Exception as e:
        logger.warning("Could not list remote branches: %s", e)
        return []


def find_matching_archive_branch(
    version_pattern: str, available_branches: list[str]
) -> str | None:
    """Finds the best matching archive branch for the requested version pattern."""
    available_versions = [b.removeprefix("archive/") for b in available_branches]

    # Exact match
    for v in available_versions:
        if v.lower() == version_pattern.lower():
            return f"origin/archive/{v}"

    # Exact match with 'xemu-' prefix
    for v in available_versions:
        if v.lower() == f"xemu-{version_pattern.lower()}":
            return f"origin/archive/{v}"

    # Regex search
    pattern_escaped = re.escape(version_pattern).replace(r"\*", ".*")
    regex = re.compile(pattern_escaped, re.IGNORECASE)
    for v in available_versions:
        if regex.search(v):
            return f"origin/archive/{v}"

    return None


def list_archive_tree_dirs(branch_ref: str, cwd: str | None = None) -> list[str]:
    """Lists all directory paths under results/ in the given archive branch ref."""
    try:
        lines = git(
            "ls-tree", "-d", "-r", "--name-only", branch_ref, "results", cwd=cwd
        ).splitlines()
        return [line.strip() for line in lines if line.strip()]
    except Exception as e:
        logger.warning("Could not list tree for %s: %s", branch_ref, e)
        return []


def find_matching_archive_paths(
    branch_ref: str, target: ResultTarget, cwd: str | None = None
) -> list[str]:
    """Finds exact directory paths inside the archive tree to extract for target."""
    tree_dirs = list_archive_tree_dirs(branch_ref, cwd=cwd)
    version_prefix = branch_ref.split("origin/archive/")[-1]

    # If no tree listing is available, fall back to version root
    if not tree_dirs:
        return [f"results/{version_prefix}"]

    # If neither platform nor renderer is specified, extract entire version tree
    if not target.platform and not target.renderer:
        return [f"results/{version_prefix}"]

    target_platform = target.platform or ""
    target_renderer = target.renderer or ""

    candidates = [d for d in tree_dirs if d.startswith(f"results/{version_prefix}")]

    # Filter by platform if known
    if target_platform:
        platform_candidates = [
            d
            for d in candidates
            if f"/{target_platform}" in d or d.endswith(f"/{target_platform}")
        ]
        if platform_candidates:
            candidates = platform_candidates

    # Match renderer
    if target_renderer:
        # Match slash-separated vs dash-separated formats
        renderer_norm = target_renderer.replace("__", "--")
        matching_dirs: list[str] = []

        for d in candidates:
            # d is e.g. results/<version>/Darwin_arm64/gl_Apple_Apple_M5_Max/gslv_4.10
            rel_after_platform = (
                d.split(f"/{target_platform}/")[-1]
                if target_platform and f"/{target_platform}/" in d
                else d
            )
            rel_norm = rel_after_platform.replace("/", "--").replace("__", "--")
            if (
                rel_norm == renderer_norm
                or renderer_norm.startswith(rel_norm)
                or rel_norm.startswith(renderer_norm)
            ):
                matching_dirs.append(d)

        if matching_dirs:
            # Pick the deepest matching directories (the leaf result directory)
            max_depth = max(d.count("/") for d in matching_dirs)
            leaf_dirs = [d for d in matching_dirs if d.count("/") == max_depth]
            return leaf_dirs

    # If platform was matched but no specific renderer directory resolved, return platform candidates
    if target_platform and candidates:
        min_depth = min(d.count("/") for d in candidates)
        return [d for d in candidates if d.count("/") == min_depth]

    return [f"results/{version_prefix}"]


def clean_comparison_caches(target: ResultTarget, target_dir: str) -> list[str]:
    """Removes existing comparison result directories for the target result."""
    removed: list[str] = []
    comp_base = os.path.join(target_dir, "compare-results")
    if not os.path.isdir(comp_base):
        return removed

    # Candidates under compare-results/<version> and compare-results/results/<version>
    version_dirs = [
        os.path.join(comp_base, target.version),
        os.path.join(comp_base, "results", target.version),
    ]

    for v_dir in version_dirs:
        if not os.path.isdir(v_dir):
            continue

        if not target.platform and not target.renderer:
            logger.info("Removing full version comparison directory: %s", v_dir)
            shutil.rmtree(v_dir, ignore_errors=True)
            removed.append(v_dir)
            continue

        target_platform = target.platform or ""
        target_renderer = (target.renderer or "").replace("__", "--")

        for root, dirs, _files in os.walk(v_dir):
            for d in list(dirs):
                full_path = os.path.join(root, d)
                rel_path = os.path.relpath(full_path, v_dir).replace("\\", "/")
                rel_norm = rel_path.replace("/", "--").replace("__", "--")

                match = False
                if target_platform and target_renderer:
                    if target_platform in rel_path and (
                        target_renderer in rel_norm or rel_norm in target_renderer
                    ):
                        match = True
                elif target_platform and rel_path == target_platform:
                    match = True

                if match:
                    logger.info("Removing comparison cache directory: %s", full_path)
                    shutil.rmtree(full_path, ignore_errors=True)
                    removed.append(full_path)

    return removed


def restore_result(
    target: ResultTarget,
    target_dir: str,
    force: bool = False,
    repo_dir: str | None = None,
) -> bool:
    """Restores result files from the archive branch for the given ResultTarget."""
    cwd = repo_dir or target_dir
    available_branches = fetch_archive_branches(cwd=cwd)

    branch_ref = find_matching_archive_branch(target.version, available_branches)
    if not branch_ref:
        logger.error(
            "Could not find matching archive branch for version '%s'. Available archive versions: %s",
            target.version,
            [b.removeprefix("archive/") for b in available_branches],
        )
        return False

    logger.info("Found archive branch: %s", branch_ref)
    paths_to_extract = find_matching_archive_paths(branch_ref, target, cwd=cwd)
    logger.info("Paths to extract: %s", paths_to_extract)

    abs_target_dir = os.path.abspath(target_dir)
    os.makedirs(abs_target_dir, exist_ok=True)

    try:
        archive_proc = subprocess.Popen(
            ["git", "archive", branch_ref, *paths_to_extract],
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
            logger.error(
                "tar extraction failed with return code %d", tar_proc.returncode
            )
            return False

        logger.info(
            "Successfully extracted %s into %s", paths_to_extract, abs_target_dir
        )

        if force:
            cleaned = clean_comparison_caches(target, target_dir)
            if cleaned:
                logger.info(
                    "Cleaned %d comparison cache directory/directories.", len(cleaned)
                )

        # Write GitHub Actions step output if running in CI
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"version={target.version}\n")
                f.write(f"platform={target.platform or ''}\n")
                f.write(f"renderer={target.renderer or ''}\n")
                f.write(f"suite={target.suite or ''}\n")
                f.write(f"archive_branch={branch_ref}\n")
                f.write(f"paths_restored={','.join(paths_to_extract)}\n")

        return True

    except Exception:
        logger.exception("Failed to restore result for %s", target)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restores archived result images from a site page URL or path."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Page URL or result path (e.g. https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/...)",
    )
    parser.add_argument(
        "--target-dir",
        default=".",
        help="Directory into which results should be extracted (default: current directory)",
    )
    parser.add_argument(
        "--repo-dir",
        help="Git repository directory containing origin remote (defaults to target-dir or current dir)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove existing comparison cache for matching result to force re-diffing",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        target = parse_result_url(args.url)
        logger.info(
            "Parsed target: version=%s, platform=%s, renderer=%s, suite=%s",
            target.version,
            target.platform,
            target.renderer,
            target.suite,
        )
    except Exception as e:
        logger.error("Failed to parse URL '%s': %s", args.url, e)
        return 1

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

    success = restore_result(
        target=target,
        target_dir=args.target_dir,
        force=args.force,
        repo_dir=repo_dir,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
