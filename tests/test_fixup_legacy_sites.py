from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

scripts_dir = str(Path(__file__).parent.parent / ".github" / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from fixup_legacy_sites import (  # noqa: E402
    collect_diff_tests,
    collect_tests_from_results_dir,
    discover_comparison_dirs,
    find_matching_results_dir,
    fixup_comparison_dir,
    reconstruct_golden_tests_from_tree,
)


def test_collect_tests_from_results_dir_pngs(tmp_path: Path) -> None:
    results_dir = tmp_path / "results_run"
    suite1 = results_dir / "2D_Lines"
    suite1.mkdir(parents=True)
    (suite1 / "Line1.png").touch()
    (suite1 / "Line2.png").touch()
    (suite1 / "Line1-diff.png").touch()  # Should be ignored

    suite2 = results_dir / "Blend_surface"
    suite2.mkdir(parents=True)
    (suite2 / "Blend1.png").touch()

    tests = collect_tests_from_results_dir(str(results_dir))
    assert tests == {
        "2D_Lines:Line1",
        "2D_Lines:Line2",
        "Blend_surface:Blend1",
    }


def test_collect_tests_from_results_dir_json(tmp_path: Path) -> None:
    results_dir = tmp_path / "results_run"
    results_dir.mkdir(parents=True)
    results_json: dict[str, Any] = {
        "passed": {"2D Lines::Line1": {}, "Blend surface::Blend1": {}},
        "failed": {"2D Lines::Line2": {}},
        "flaky": {},
    }
    with open(results_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results_json, f)

    tests = collect_tests_from_results_dir(str(results_dir))
    assert tests == {
        "2D_Lines:Line1",
        "2D_Lines:Line2",
        "Blend_surface:Blend1",
    }


def test_collect_diff_tests(tmp_path: Path) -> None:
    comp_dir = tmp_path / "compare_run"
    suite1 = comp_dir / "2D_Lines"
    suite1.mkdir(parents=True)
    (suite1 / "Line1-diff.png").touch()
    (suite1 / "Line2-diff.png").touch()
    (suite1 / "other.png").touch()  # Should be ignored

    diffs = collect_diff_tests(str(comp_dir))
    assert diffs == {"2D_Lines:Line1", "2D_Lines:Line2"}


def test_find_matching_results_dir(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    version = "xemu-0.8.136"
    platform = "Darwin_arm64"

    # Case 1: direct renderer match
    dir1 = results_root / version / platform / "gl_Apple_M5--gslv_4.10"
    dir1.mkdir(parents=True)

    found = find_matching_results_dir(
        str(results_root), version, platform, "gl_Apple_M5--gslv_4.10"
    )
    assert found == str(dir1)

    # Case 2: slash separated in results (vendor / glsl)
    dir2 = results_root / version / "Linux_x86_64" / "gl_NVIDIA" / "gslv_4.00"
    dir2.mkdir(parents=True)

    found2 = find_matching_results_dir(
        str(results_root), version, "Linux_x86_64", "gl_NVIDIA--gslv_4.00"
    )
    assert found2 == str(dir2)

    # Case 3: legacy double underscore in compare-results matching canonical in results
    found3 = find_matching_results_dir(
        str(results_root), version, "Linux_x86_64", "gl_NVIDIA__gslv_4.00"
    )
    assert found3 == str(dir2)


def test_fixup_comparison_dir_corrupted_darwin(tmp_path: Path) -> None:
    version = "xemu-0.8.136-fc24584ce88f0915ad7f04775bb7712c2e3f49ee"
    platform = "Darwin_arm64"
    renderer = "gl_Apple_Apple_M5_Max--gslv_4.10"
    target = "Xbox--Xbox--DirectX--nv2a"

    # Create results directory with 10 tests
    results_root = tmp_path / "results"
    run_results_dir = (
        results_root
        / version
        / platform
        / "gl_Apple_Apple_M5_Max"
        / "gslv_4.10"
        / "SuiteA"
    )
    run_results_dir.mkdir(parents=True)
    for i in range(10):
        (run_results_dir / f"Test{i}.png").touch()

    # Create comparison directory with 4 diffs (Test0, Test1, Test2, Test3)
    comp_base = tmp_path / "compare-results"
    comp_dir = comp_base / version / platform / renderer / target
    comp_suite_dir = comp_dir / "SuiteA"
    comp_suite_dir.mkdir(parents=True)
    for i in range(4):
        (comp_suite_dir / f"Test{i}-diff.png").touch()

    # Create corrupted existing summary:
    # missing Test4 and Test5 from tests_without_goldens (partition bug!)
    corrupted_summary = {
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": ["SuiteB:Gold1", "SuiteB:Gold2"],
        "result_identifier": f"{version}:{platform}:gl_Apple_Apple_M5_Max:gslv_4.10",
        "tests_evaluated": [f"SuiteA:Test{i}" for i in range(10)],
        "tests_with_differences": {f"SuiteA:Test{i}": "200" for i in range(4)},
        # Intentionally missing Test4 and Test5 (only has Test6..9)
        "tests_without_goldens": [f"SuiteA:Test{i}" for i in range(6, 10)],
    }
    with open(comp_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(corrupted_summary, f, indent=2)

    golden_tests = {f"SuiteA:Test{i}" for i in range(10)} | {
        "SuiteB:Gold1",
        "SuiteB:Gold2",
    }

    modified = fixup_comparison_dir(
        str(comp_dir),
        str(results_root),
        golden_tests,
        dry_run=False,
    )
    assert modified is True

    # Check updated summary
    with open(comp_dir / "summary.json", encoding="utf-8") as f:
        updated = json.load(f)

    assert len(updated["tests_evaluated"]) == 10
    assert len(updated["tests_with_differences"]) == 4
    # All 6 non-diff tests recovered: Test4, Test5, Test6, Test7, Test8, Test9
    assert len(updated["tests_without_goldens"]) == 6
    assert len(updated["tests_with_differences"]) + len(
        updated["tests_without_goldens"]
    ) == len(updated["tests_evaluated"])
    assert updated["tests_without_goldens"] == [f"SuiteA:Test{i}" for i in range(4, 10)]
    # Goldens without results
    assert updated["goldens_without_results"] == [
        "SuiteB:Gold1",
        "SuiteB:Gold2",
    ]
    # Preserved score
    assert updated["tests_with_differences"]["SuiteA:Test0"] == "200"


def test_fixup_comparison_dir_already_valid_linux(tmp_path: Path) -> None:
    version = "xemu-0.8.136"
    platform = "Linux_x86_64"
    renderer = "gl_NVIDIA--gslv_4.00"
    target = "Xbox--Xbox--DirectX--nv2a"

    results_root = tmp_path / "results"
    run_results_dir = (
        results_root / version / platform / "gl_NVIDIA" / "gslv_4.00" / "SuiteA"
    )
    run_results_dir.mkdir(parents=True)
    for i in range(5):
        (run_results_dir / f"Test{i}.png").touch()

    comp_base = tmp_path / "compare-results"
    comp_dir = comp_base / version / platform / renderer / target
    comp_suite_dir = comp_dir / "SuiteA"
    comp_suite_dir.mkdir(parents=True)
    (comp_suite_dir / "Test0-diff.png").touch()
    (comp_suite_dir / "Test1-diff.png").touch()

    golden_tests = {f"SuiteA:Test{i}" for i in range(5)} | {"SuiteB:Golden1"}

    # Already valid summary
    valid_summary = {
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": ["SuiteB:Golden1"],
        "result_identifier": f"{version}:{platform}:gl_NVIDIA:gslv_4.00",
        "tests_evaluated": [f"SuiteA:Test{i}" for i in range(5)],
        "tests_with_differences": {
            "SuiteA:Test0": "100",
            "SuiteA:Test1": "200",
        },
        "tests_without_goldens": ["SuiteA:Test2", "SuiteA:Test3", "SuiteA:Test4"],
    }
    with open(comp_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(valid_summary, f, indent=2, sort_keys=True)
        f.write("\n")

    modified = fixup_comparison_dir(
        str(comp_dir),
        str(results_root),
        golden_tests,
        dry_run=False,
    )
    assert modified is False


def test_reconstruct_golden_tests_from_tree(tmp_path: Path) -> None:
    comp_base = tmp_path / "compare-results"
    run1 = comp_base / "v1" / "p1" / "r1" / "Xbox--Xbox--DirectX--nv2a"
    run1.mkdir(parents=True)

    summary_data = {
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": [f"SuiteB:G{i}" for i in range(2500)],
        "tests_evaluated": [f"SuiteA:T{i}" for i in range(3500)],
        "tests_with_differences": {},
        "tests_without_goldens": [],
    }
    with open(run1 / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f)

    reconstructed = reconstruct_golden_tests_from_tree(str(comp_base))
    assert len(reconstructed) == 6000
    assert "SuiteA:T0" in reconstructed
    assert "SuiteB:G0" in reconstructed


def test_discover_comparison_dirs(tmp_path: Path) -> None:
    comp_base = tmp_path / "compare-results"
    dir1 = comp_base / "v1" / "p1" / "r1" / "Xbox--Xbox--DirectX--nv2a"
    dir1.mkdir(parents=True)
    (dir1 / "summary.json").touch()

    dir2 = comp_base / "v2" / "p2" / "r2" / "Xbox__Xbox__DirectX__nv2a"
    dir2.mkdir(parents=True)

    non_comp = comp_base / "v1" / "p1" / "other"
    non_comp.mkdir(parents=True)

    found = discover_comparison_dirs(str(comp_base))
    assert set(found) == {str(dir1), str(dir2)}
