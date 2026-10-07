#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from xemu_pgraph_ci_tools.comparator import reduce_comparison_summaries
from xemu_pgraph_ci_tools.golden_config import (
    DEFAULT_HW_GOLDEN_CONFIG_URL,
    load_golden_config,
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge shard summary files into unified summary.json files."
    )
    parser.add_argument(
        "--comparison-dir",
        default="compare-results",
        help="Root directory containing comparison results",
    )
    parser.add_argument(
        "--golden-config",
        default=None,
        help="Path to golden config.json file",
    )
    parser.add_argument(
        "--golden-config-url",
        default=DEFAULT_HW_GOLDEN_CONFIG_URL,
        help="URL for golden config.json",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    reduce_comparison_summaries(args.comparison_dir)

    golden_config = load_golden_config(
        config_path=args.golden_config,
        config_url=args.golden_config_url,
    )
    if golden_config.has_deprecated_tests and os.path.isdir(args.comparison_dir):
        for root, _dirs, files in os.walk(args.comparison_dir):
            if "summary.json" in files:
                summary_file = os.path.join(root, "summary.json")
                try:
                    with open(summary_file, encoding="utf-8") as f:
                        data = json.load(f)
                    changed = False
                    if "goldens_without_results" in data:
                        orig = data["goldens_without_results"]
                        filtered = [
                            t for t in orig if not golden_config.is_deprecated_fq(t)
                        ]
                        if len(filtered) != len(orig):
                            data["goldens_without_results"] = filtered
                            changed = True
                    if "tests_with_differences" in data:
                        orig_diffs = data["tests_with_differences"]
                        filtered_diffs = {
                            k: v
                            for k, v in orig_diffs.items()
                            if not golden_config.is_deprecated_fq(k)
                        }
                        if len(filtered_diffs) != len(orig_diffs):
                            data["tests_with_differences"] = filtered_diffs
                            changed = True
                    if changed:
                        with open(summary_file, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2)
                        logger.info("Stripped deprecated tests from %s", summary_file)
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(
                        "Could not filter deprecated tests from %s: %s",
                        summary_file,
                        e,
                    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
