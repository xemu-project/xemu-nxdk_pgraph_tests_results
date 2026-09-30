#!/usr/bin/env python3


# ruff: noqa: BLE001 Do not catch blind exception: `Exception`

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)


def git(*args):
    return subprocess.check_output(["git", *list(args)]).decode().strip()


def git_mktree(entries):
    return (
        subprocess.check_output(["git", "mktree"], input="\n".join(entries).encode())
        .decode()
        .strip()
    )


def sync_version(version: str, remote_branches) -> bool:
    branch_name = f"archive/{version}"
    print(f"Checking {version}...")

    try:
        remote_ref = f"refs/remotes/origin/{branch_name}"
        res_v_sha = git("rev-parse", f"HEAD:results/{version}")

        # If HEAD:results/{version} lacks PNGs but remote archive already has them, preserve remote tree
        if branch_name in remote_branches:
            try:
                head_files = git(
                    "ls-tree", "-r", "--name-only", f"HEAD:results/{version}"
                ).splitlines()
                if not any(f.endswith(".png") for f in head_files):
                    remote_res_v_sha = git(
                        "rev-parse", f"{remote_ref}:results/{version}"
                    )
                    remote_files = git(
                        "ls-tree",
                        "-r",
                        "--name-only",
                        f"{remote_ref}:results/{version}",
                    ).splitlines()
                    if any(f.endswith(".png") for f in remote_files):
                        res_v_sha = remote_res_v_sha
            except Exception as e:
                logger.debug("Failed checking remote results tree: %s", e)

        issues_blob = git("rev-parse", "HEAD:results/known_issues.json")

        results_tree_entries = [
            f"040000 tree {res_v_sha}\t{version}",
            f"100644 blob {issues_blob}\tknown_issues.json",
        ]
        results_sub_tree_hash = git_mktree(results_tree_entries)

        root_entries = [f"040000 tree {results_sub_tree_hash}\tresults"]

        try:
            comp_v_sha = git("rev-parse", f"HEAD:compare-results/{version}")
            comp_sub_tree_hash = git_mktree([f"040000 tree {comp_v_sha}\t{version}"])
            root_entries.append(f"040000 tree {comp_sub_tree_hash}\tcompare-results")
        except Exception:  # noqa: S110 `try`-`except`-`pass` detected, consider logging the exception
            # Not every version will have diffs generated yet
            pass

        root_tree_hash = git_mktree(root_entries)
        if branch_name in remote_branches:
            remote_sha = git("rev-parse", remote_ref)
            remote_tree = git("rev-parse", f"{remote_sha}^{{tree}}")
            if remote_tree == root_tree_hash:
                print(f"  [S] {version} is up to date.")
                return True

        new_commit = git(
            "commit-tree", root_tree_hash, "-m", f"Archive results for {version}"
        )
        print(f"  [P] Updating {branch_name}...")
        git("push", "origin", f"{new_commit}:refs/heads/{branch_name}", "--force")
        return True

    except Exception:
        logger.exception("  [!] Failed to sync %s", version)
        return False


if __name__ == "__main__":
    branches = git("branch", "-r").split()
    remote_archive_branches = [
        b.split("origin/")[1] for b in branches if "origin/archive/" in b
    ]

    versions = [
        d for d in os.listdir("results") if os.path.isdir(os.path.join("results", d))
    ]

    success = True
    for v in versions:
        if not sync_version(v, remote_archive_branches):
            success = False

    if not success:
        print("\nFinished with errors.")
        sys.exit(1)
