from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

scripts_dir = str(Path(__file__).parent.parent / ".github" / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

for candidate in [
    Path(__file__).resolve().parents[3] / "xemu-pgraph-ci-tools" / "src",
    Path(__file__).resolve().parents[2] / "xemu-pgraph-ci-tools" / "src",
]:
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from xemu_pgraph_ci_tools.golden_config import GoldenConfig

if "xemu_pgraph_ci_tools.hw_diffs" not in sys.modules:
    sys.modules["xemu_pgraph_ci_tools.hw_diffs"] = MagicMock()

import plan_hw_diffs


def test_plan_hw_diffs_filters_deprecated_tasks(tmp_path: Path) -> None:
    task1 = MagicMock()
    task1.suite = "Blend_tests"
    task1.test_case = "0_ADD_1"
    task1.to_dict.return_value = {"suite": "Blend_tests", "test": "0_ADD_1"}

    task2 = MagicMock()
    task2.suite = "Valid_suite"
    task2.test_case = "Valid_test"
    task2.to_dict.return_value = {"suite": "Valid_suite", "test": "Valid_test"}

    mock_identify = MagicMock(return_value=[task1, task2])
    golden_config = GoldenConfig(deprecated_tests={"Blend_tests": ["0_ADD_1"]})

    output_plan = tmp_path / "diff_tasks.json"

    with (
        patch("plan_hw_diffs.identify_missing_hw_diffs", mock_identify),
        patch("plan_hw_diffs.load_golden_config", return_value=golden_config),
        patch("plan_hw_diffs.GitWorkTree"),
        patch(
            "sys.argv",
            [
                "plan_hw_diffs.py",
                "--output-plan-file",
                str(output_plan),
            ],
        ),
    ):
        ret = plan_hw_diffs.main()
        assert ret == 0

    assert output_plan.exists()
    import json

    plan_data = json.loads(output_plan.read_text(encoding="utf-8"))
    assert len(plan_data) == 1
    assert plan_data[0]["suite"] == "Valid_suite"
    assert plan_data[0]["test"] == "Valid_test"
