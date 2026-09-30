from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

scripts_dir = str(Path(__file__).parent.parent / ".github" / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from restore_result_from_url import (  # noqa: E402
    clean_comparison_caches,
    find_matching_archive_branch,
    find_matching_archive_paths,
    parse_result_url,
    ResultTarget,
)


class TestRestoreResultFromUrl(unittest.TestCase):
    def test_parse_full_result_index_url(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max--gslv_4.10/index.html"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertEqual(target.platform, "Darwin_arm64")
        self.assertEqual(target.renderer, "gl_Apple_Apple_M5_Max--gslv_4.10")
        self.assertIsNone(target.suite)

    def test_parse_suite_page_url(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max--gslv_4.10/2D_Lines/index.html"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertEqual(target.platform, "Darwin_arm64")
        self.assertEqual(target.renderer, "gl_Apple_Apple_M5_Max--gslv_4.10")
        self.assertEqual(target.suite, "2D_Lines")

    def test_parse_compare_url(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/compare/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max--gslv_4.10/Xbox_Hardware/index.html"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertEqual(target.platform, "Darwin_arm64")
        self.assertEqual(target.renderer, "gl_Apple_Apple_M5_Max--gslv_4.10")
        self.assertIsNone(target.suite)

    def test_parse_colon_composite_compare_url(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/compare/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee:Darwin_arm64:gl_Apple_Apple_M5_Max:gslv_4.10/Xbox_Hardware/index.html"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertEqual(target.platform, "Darwin_arm64")
        self.assertEqual(target.renderer, "gl_Apple_Apple_M5_Max--gslv_4.10")

    def test_parse_slash_vendor_and_glsl(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Linux_x86_64/gl_Mesa_NV134/gslv_4.30/index.html"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertEqual(target.platform, "Linux_x86_64")
        self.assertEqual(target.renderer, "gl_Mesa_NV134--gslv_4.30")

    def test_parse_version_only_url(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertIsNone(target.platform)
        self.assertIsNone(target.renderer)

    def test_parse_relative_path(self) -> None:
        path = "results/xemu-0.8.135-6318bb112091635ef908255019e4d42956bc5fa8/Darwin_arm64/gl_Apple_Apple_M5_Max--gslv_4.10/index.html"
        target = parse_result_url(path)
        self.assertEqual(
            target.version, "xemu-0.8.135-6318bb112091635ef908255019e4d42956bc5fa8"
        )
        self.assertEqual(target.platform, "Darwin_arm64")
        self.assertEqual(target.renderer, "gl_Apple_Apple_M5_Max--gslv_4.10")

    def test_parse_url_with_query_and_anchor(self) -> None:
        url = "https://xemu-project.github.io/xemu-nxdk_pgraph_tests_results/results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max--gslv_4.10/index.html?view=all#Blend_surface"
        target = parse_result_url(url)
        self.assertEqual(
            target.version, "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )
        self.assertEqual(target.platform, "Darwin_arm64")
        self.assertEqual(target.renderer, "gl_Apple_Apple_M5_Max--gslv_4.10")

    def test_find_matching_archive_branch(self) -> None:
        available = [
            "archive/xemu-0.8.135-6318bb112091635ef908255019e4d42956bc5fa8",
            "archive/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee",
            "archive/xemu-0.7.98-master-7bfb7c85378f64f93556c365ea0cc18cb2181dc8",
        ]
        # Exact match
        b1 = find_matching_archive_branch(
            "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee", available
        )
        self.assertEqual(
            b1, "origin/archive/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )

        # Fuzzy version match
        b2 = find_matching_archive_branch("0.8.136", available)
        self.assertEqual(
            b2, "origin/archive/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )

    def test_find_matching_archive_paths(self) -> None:
        target = ResultTarget(
            version="xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee",
            platform="Darwin_arm64",
            renderer="gl_Apple_Apple_M5_Max--gslv_4.10",
        )
        branch_ref = (
            "origin/archive/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
        )

        # Mock list_archive_tree_dirs behavior by passing a function or verifying mock tree
        from unittest.mock import patch

        mock_tree = [
            "results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64",
            "results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max",
            "results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max/gslv_4.10",
            "results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Linux_x86_64/gl_Mesa/gslv_4.50",
        ]

        with patch(
            "restore_result_from_url.list_archive_tree_dirs", return_value=mock_tree
        ):
            paths = find_matching_archive_paths(branch_ref, target)
            self.assertEqual(
                paths,
                [
                    "results/xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee/Darwin_arm64/gl_Apple_Apple_M5_Max/gslv_4.10"
                ],
            )

    def test_clean_comparison_caches(self) -> None:
        tmp_dir = Path("/tmp") / "test_clean_comp_cache"
        comp_dir = (
            tmp_dir
            / "compare-results"
            / "xemu-0.8.136"
            / "Darwin_arm64"
            / "gl_Apple_Apple_M5_Max"
            / "gslv_4.10"
        )
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "summary.json").touch()

        other_comp_dir = (
            tmp_dir
            / "compare-results"
            / "xemu-0.8.136"
            / "Linux_x86_64"
            / "gl_Mesa"
            / "gslv_4.50"
        )
        other_comp_dir.mkdir(parents=True, exist_ok=True)
        (other_comp_dir / "summary.json").touch()

        target = ResultTarget(
            version="xemu-0.8.136",
            platform="Darwin_arm64",
            renderer="gl_Apple_Apple_M5_Max--gslv_4.10",
        )

        cleaned = clean_comparison_caches(target, str(tmp_dir))
        self.assertTrue(any(str(comp_dir) in c for c in cleaned))
        self.assertFalse(os.path.exists(comp_dir))
        self.assertTrue(os.path.exists(other_comp_dir))


if __name__ == "__main__":
    unittest.main()
