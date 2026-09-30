#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import sys

from xemu_pgraph_ci_tools.comparator import reduce_comparison_summaries

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

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    reduce_comparison_summaries(args.comparison_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
