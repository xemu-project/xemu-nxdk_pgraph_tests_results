#!/usr/bin/env python3

from __future__ import annotations

import os
import sys


def main():
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        print(f"Error: {readme_path} not found")
        sys.exit(1)

    with open(readme_path, encoding="utf-8") as f:
        content = f.read()

    start_marker = "# Updating"
    end_marker = "# Advanced"

    start_idx = content.find(start_marker)
    if start_idx == -1:
        print(f"Error: Could not find '{start_marker}' in README.md")
        sys.exit(1)

    end_idx = content.find(end_marker, start_idx)
    extracted = content[start_idx:] if end_idx == -1 else content[start_idx:end_idx]

    extracted = extracted.strip() + "\n"

    header = "# xemu-nxdk_pgraph_tests_results User Scripts\n\n"
    final_content = header + extracted

    os.makedirs("dist", exist_ok=True)
    with open("dist/README.md", "w", encoding="utf-8") as f:
        f.write(final_content)
    print("Successfully extracted README instructions to dist/README.md")


if __name__ == "__main__":
    main()
