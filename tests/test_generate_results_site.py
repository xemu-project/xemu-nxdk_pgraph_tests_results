from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import MagicMock

# Mock third-party dependencies not present in default test environment
for mod in [
    "requests",
    "jinja2",
    "frozendict",
    "xemu_pgraph_ci_tools",
    "xemu_pgraph_ci_tools.models",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Minimal frozendict mock if needed
import frozendict  # noqa: E402

if isinstance(frozendict.frozendict, MagicMock):
    frozendict.frozendict = dict
    frozendict.deepfreeze = lambda x: x

from xemu_pgraph_ci_tools.models import RunIdentifier  # noqa: E402

if isinstance(RunIdentifier, MagicMock):

    class DummyRunIdentifier:
        def __init__(
            self,
            xemu_version: str = "v1",
            platform_info: str = "p1",
            gl_info: str = "gl1",
        ) -> None:
            self.xemu_version = xemu_version
            self.platform_info = platform_info
            self.gl_info = gl_info
            self.minimal_path = f"{xemu_version}/{platform_info}/{gl_info}"

        @classmethod
        def parse(cls, s: str) -> DummyRunIdentifier:
            parts = s.split("/")
            return cls(
                parts[-3] if len(parts) >= 3 else "v1",
                parts[-2] if len(parts) >= 2 else "p1",
                parts[-1] if parts else "gl1",
            )

        def minimal_identifier(self) -> DummyRunIdentifier:
            return self

    sys.modules["xemu_pgraph_ci_tools.models"].RunIdentifier = DummyRunIdentifier

scripts_dir = str(Path(__file__).parent.parent / ".github" / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from generate_results_site import (  # noqa: E402
    PagesWriter,
    ResultsInfo,
    ResultsScanner,
    SuiteResults,
    TestResult,
    _normalize_results_summary,
)

TestResult.__test__ = False


def test_normalize_results_summary_spaces_and_swapped_names() -> None:
    raw = {
        "passed": {
            "Texture format::TexFmt_A1": {
                "name": "TexFmt_A1",
                "suite": "Texture format",
                "duration_milliseconds": 100,
            }
        },
        "failed": {
            "Texture format::DepthFmt_D1": {
                "name": "Texture format",  # Swapped by runner
                "suite": "DepthFmt_D1",  # Swapped by runner
                "failures": ["error 1"],
            },
            "Clear::SCF_1": {
                "name": "Clear",
                "suite": "SCF_1",
                "failures": ["error 2"],
            },
        },
        "flaky": {
            "Color zeta overlap::Zeta1": {
                "name": "Zeta1",
                "suite": "Color zeta overlap",
                "failures": ["flaky error"],
            }
        },
    }

    norm = _normalize_results_summary(raw)

    # Check passed
    assert "Texture_format::TexFmt_A1" in norm["passed"]
    assert "Texture format::TexFmt_A1" not in norm["passed"]
    assert norm["passed"]["Texture_format::TexFmt_A1"]["suite"] == "Texture_format"
    assert norm["passed"]["Texture_format::TexFmt_A1"]["name"] == "TexFmt_A1"

    # Check failed (and inverted name/suite fix)
    assert "Texture_format::DepthFmt_D1" in norm["failed"]
    assert norm["failed"]["Texture_format::DepthFmt_D1"]["suite"] == "Texture_format"
    assert norm["failed"]["Texture_format::DepthFmt_D1"]["name"] == "DepthFmt_D1"

    assert "Clear::SCF_1" in norm["failed"]
    assert norm["failed"]["Clear::SCF_1"]["suite"] == "Clear"
    assert norm["failed"]["Clear::SCF_1"]["name"] == "SCF_1"

    # Check flaky
    assert "Color_zeta_overlap::Zeta1" in norm["flaky"]
    assert norm["flaky"]["Color_zeta_overlap::Zeta1"]["suite"] == "Color_zeta_overlap"
    assert norm["flaky"]["Color_zeta_overlap::Zeta1"]["name"] == "Zeta1"


def test_process_suite_matches_normalized_results(tmp_path: Path) -> None:
    scanner = ResultsScanner(
        results_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        base_url="https://example.com",
        run_identifier_to_comparison_results={},
        test_suite_descriptors={},
    )

    suite_dir = tmp_path / "Texture_format"
    suite_dir.mkdir(parents=True)
    (suite_dir / "TexFmt_A1.png").touch()

    raw_summary = {
        "passed": {
            "Texture format::TexFmt_A1": {
                "name": "TexFmt_A1",
                "suite": "Texture format",
                "duration_milliseconds": 50,
            }
        },
        "failed": {
            "Texture format::DepthFmt_D1": {
                "name": "Texture format",
                "suite": "DepthFmt_D1",
                "failures": ["shader fail"],
            }
        },
        "flaky": {},
    }
    normalized_summary = _normalize_results_summary(raw_summary)

    suite_result = scanner._process_suite(
        str(suite_dir), "Texture_format", normalized_summary
    )

    assert suite_result is not None
    assert suite_result.name == "Texture_format"
    assert len(suite_result.test_results) == 1
    assert suite_result.test_results[0].name == "TexFmt_A1"
    # Metadata should be found and attached
    assert suite_result.test_results[0].info["duration_milliseconds"] == 50

    # Failures should be attached to this suite
    assert "Texture_format::DepthFmt_D1" in suite_result.failed_tests
    assert suite_result.failed_tests["Texture_format::DepthFmt_D1"]["failures"] == [
        "shader fail"
    ]


def test_process_results_no_duplicate_suites_and_multiple_failures(
    tmp_path: Path,
) -> None:
    scanner = ResultsScanner(
        results_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        base_url="https://example.com",
        run_identifier_to_comparison_results={},
        test_suite_descriptors={},
    )

    run_dir = tmp_path / "v1" / "p1" / "gl1"
    suite_dir = run_dir / "Texture_format"
    suite_dir.mkdir(parents=True)
    (suite_dir / "TexFmt_A1.png").touch()

    raw_summary = {
        "passed": {
            "Texture format::TexFmt_A1": {"duration": 10},
        },
        "failed": {
            "Texture format::DepthFmt_D1": {"failures": ["fail 1"]},
            "Texture format::DepthFmt_D2": {"failures": ["fail 2"]},
            "Completely_Broken::Test1": {"failures": ["broken 1"]},
            "Completely_Broken::Test2": {"failures": ["broken 2"]},
        },
        "flaky": {},
    }
    normalized_summary = _normalize_results_summary(raw_summary)

    results_info = scanner._process_results(
        str(run_dir), ["Machine: info"], normalized_summary
    )

    suite_names = [s.name for s in results_info.results]
    # No duplicate "Texture format" with space
    assert "Texture_format" in suite_names
    assert "Texture format" not in suite_names

    # The suite with no artifacts should collect ALL its failures
    broken_suite = next(
        s for s in results_info.results if s.name == "Completely_Broken"
    )
    assert len(broken_suite.failed_tests) == 2
    assert "Completely_Broken::Test1" in broken_suite.failed_tests
    assert "Completely_Broken::Test2" in broken_suite.failed_tests


def test_write_test_suite_results_page_uses_test_name(tmp_path: Path) -> None:
    env_mock = MagicMock()
    template_mock = MagicMock()
    template_mock.render.return_value = "<html>mock</html>"
    env_mock.get_template.return_value = template_mock

    writer = PagesWriter(
        results={},
        env=env_mock,
        output_dir=str(tmp_path / "site"),
        result_images_base_url="https://example.com/images",
        hw_golden_images_base_url="https://example.com/hw_images",
        test_source_base_url="https://example.com/src",
        hw_golden_browser_base_url="https://example.com/golden",
    )

    run_id = sys.modules["xemu_pgraph_ci_tools.models"].RunIdentifier("v1", "p1", "gl1")
    run_info = ResultsInfo(
        identifier=run_id,
        machine_info=["CPU: Test"],
        renderer_info={"vulkan": False},
        runner_info={},
        results=(),
        comparisons=[],
    )

    suite = SuiteResults(
        name="Texture_format",
        test_results=(
            TestResult(name="TexFmt_A1", artifact_url="http://img.png", info={}),
        ),
        flaky_tests={},
        failed_tests={
            "Texture_format::DepthFmt_D1": {
                "name": "Texture format",  # Swapped name/suite
                "suite": "DepthFmt_D1",
                "failures": ["error msg"],
            }
        },
        descriptor=None,
    )

    writer._write_test_suite_results_page(run_info, suite)

    assert template_mock.render.called
    render_args = template_mock.render.call_args[1]
    results_map = render_args["results"]

    # Must be indexed by the test name "DepthFmt_D1", NOT "Texture format"
    assert "DepthFmt_D1" in results_map
    assert results_map["DepthFmt_D1"]["failures"] == ["error msg"]
    assert "Texture format" not in results_map


def test_write_run_results_pages_removes_stale_directories(tmp_path: Path) -> None:
    env_mock = MagicMock()
    template_mock = MagicMock()
    template_mock.render.return_value = "<html>mock</html>"
    env_mock.get_template.return_value = template_mock

    site_dir = tmp_path / "site"
    writer = PagesWriter(
        results={},
        env=env_mock,
        output_dir=str(site_dir),
        result_images_base_url="https://example.com/images",
        hw_golden_images_base_url="https://example.com/hw_images",
        test_source_base_url="https://example.com/src",
        hw_golden_browser_base_url="https://example.com/golden",
    )

    run_id = sys.modules["xemu_pgraph_ci_tools.models"].RunIdentifier("v1", "p1", "gl1")
    # Pre-create output dir with a stale "Texture format" directory (with space)
    run_output_dir = site_dir / "results" / "v1" / "p1" / "gl1"
    stale_suite_dir = run_output_dir / "Texture format"
    stale_suite_dir.mkdir(parents=True)
    (stale_suite_dir / "index.html").touch()

    suite = SuiteResults(
        name="Texture_format",
        test_results=(),
        flaky_tests={},
        failed_tests={},
        descriptor=None,
    )
    run_info = ResultsInfo(
        identifier=run_id,
        machine_info=["CPU: Test"],
        renderer_info={"vulkan": False},
        runner_info={},
        results=(suite,),
        comparisons=[],
    )

    writer._write_run_results_pages(run_info)

    # Stale directory "Texture format" should have been removed
    assert not stale_suite_dir.exists()
    # Active suite directory "Texture_format" should exist
    assert (run_output_dir / "Texture_format").exists()
