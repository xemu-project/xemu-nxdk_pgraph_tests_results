#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from xemu_pgraph_ci_tools.hw_diffs import identify_missing_hw_diffs

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan HW diff matrix for GitHub Actions."
    )
    parser.add_argument(
        "--results-dir", default="results", help="Directory containing test outputs"
    )
    parser.add_argument(
        "--output-dir",
        default="compare-results",
        help="Directory containing diff results",
    )
    parser.add_argument(
        "--golden-dir", default=None, help="Directory containing golden HW results"
    )
    parser.add_argument(
        "--cache-path", default="cache", help="Directory for caching downloaded goldens"
    )
    parser.add_argument(
        "--max-shards", type=int, default=32, help="Maximum number of parallel shards"
    )
    parser.add_argument(
        "--output-plan-file",
        default="diff_tasks.json",
        help="File to write the planned tasks JSON array",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    tasks = identify_missing_hw_diffs(
        results_dir=args.results_dir,
        output_dir=args.output_dir,
        golden_dir=args.golden_dir,
        cache_path=args.cache_path,
    )

    diff_count = len(tasks)
    shard_count = min(diff_count, args.max_shards) if diff_count > 0 else 0
    shards = list(range(shard_count)) if shard_count > 0 else []
    matrix = {"shard": shards}

    logger.info("Planned %d diff task(s) across %d shard(s)", diff_count, shard_count)

    if args.output_plan_file:
        os.makedirs(
            os.path.dirname(os.path.abspath(args.output_plan_file)), exist_ok=True
        )
        with open(args.output_plan_file, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in tasks], f, indent=2)
        logger.info("Saved plan to %s", args.output_plan_file)

    matrix_json = json.dumps(matrix)
    print(f"diff_count={diff_count}")
    print(f"shard_count={shard_count}")
    print(f"matrix={matrix_json}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"diff_count={diff_count}\n")
            f.write(f"shard_count={shard_count}\n")
            f.write(f"matrix={matrix_json}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
