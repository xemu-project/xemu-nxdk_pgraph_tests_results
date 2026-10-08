from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

for candidate in [
    Path(__file__).resolve().parents[3] / "xemu-pgraph-ci-tools" / "src",
    Path(__file__).resolve().parents[2] / "xemu-pgraph-ci-tools" / "src",
]:
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

# Mock third-party dependencies not present in default test environment
for mod in [
    "requests",
    "jinja2",
    "frozendict",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Minimal frozendict mock if needed
import frozendict

if isinstance(frozendict.frozendict, MagicMock):
    frozendict.frozendict = dict
    frozendict.deepfreeze = lambda x: x

from xemu_pgraph_ci_tools.models import RunIdentifier

if isinstance(RunIdentifier, MagicMock):

    class DummyRunIdentifier:
        def __init__(
            self,
            xemu_version: str = "v1",
            platform_info: str = "p1",
            gl_info: str = "gl1",
            *args,
            run_identifier: Any = None,
            **kwargs,
        ) -> None:
            self.xemu_version = xemu_version
            self.platform_info = platform_info
            self.gl_info = gl_info
            self.minimal_path = f"{xemu_version}/{platform_info}/{gl_info}"

        @classmethod
        def parse(cls, s: str) -> DummyRunIdentifier:
            if ":" in s:
                parts = s.split(":")
                gl = (
                    f"{parts[2]}--{parts[3]}"
                    if len(parts) >= 4
                    else (parts[2] if len(parts) >= 3 else "gl1")
                )
                return cls(
                    parts[0] if len(parts) >= 1 else "v1",
                    parts[1] if len(parts) >= 2 else "p1",
                    gl,
                )
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

from generate_results_site import (
    ComparisonInfo,
    ComparisonScanner,
    PagesWriter,
    PrettyMachineInfo,
    ResultsInfo,
    ResultsScanner,
    SourceTestIdentifier,
    SuiteResults,
    TestResult,
    TestSuiteComparisonInfo,
    _index_source_images,
    _normalize_results_summary,
)
from xemu_pgraph_ci_tools.golden_config import GoldenConfig

TestResult.__test__ = False
TestSuiteComparisonInfo.__test__ = False


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
    run_info = ResultsInfo(
        identifier=run_id,
        machine_info=["CPU: Test"],
        renderer_info={"vulkan": False},
        runner_info={},
        results=(suite,),
        comparisons=[],
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


def _make_results_info(
    xemu_version: str,
    platform: str,
    gl_info: str,
    machine_info: list[str],
    *,
    is_vulkan: bool = False,
) -> ResultsInfo:
    RunIdentClass = sys.modules["xemu_pgraph_ci_tools.models"].RunIdentifier
    run_id = RunIdentClass(
        xemu_version=xemu_version,
        platform_info=platform,
        gl_info=gl_info,
    )
    return ResultsInfo(
        identifier=run_id,
        machine_info=machine_info,
        renderer_info={"vulkan": is_vulkan},
        runner_info={},
        results=(),
        comparisons=[],
    )


def test_pretty_machine_info_platform_not_split_by_cpu_or_os() -> None:
    gl_machine_info = [
        "xemu_version: 0.8.136",
        "CPU: AMD EPYC 9V74 80-Core Processor",
        "OS_Version: Ubuntu 24.04.4 LTS",
        "GL_VENDOR: Mesa",
        "GL_RENDERER: llvmpipe (LLVM 20.1.2, 256 bits)",
        "GL_VERSION: 4.5 (Core Profile) Mesa 25.2.8-0ubuntu0.24.04.2",
        "GL_SHADING_LANGUAGE_VERSION: 4.50",
    ]
    gl_info = _make_results_info(
        "xemu-0.8.136",
        "Linux_x86_64",
        "gl_Mesa_llvmpipe--gslv_4.50",
        gl_machine_info,
        is_vulkan=False,
    )
    pretty_gl = PrettyMachineInfo.parse(gl_info)
    assert pretty_gl.platform == "Linux_x86_64"
    assert pretty_gl.renderer == "OpenGL"
    assert (
        pretty_gl.gl
        == "Mesa - llvmpipe (LLVM 20.1.2, 256 bits) - 4.5 (Core Profile) Mesa 25.2.8-0ubuntu0.24.04.2"
    )
    assert pretty_gl.glsl == "4.50"

    vk_machine_info = [
        "xemu_version: 0.8.136",
        "CPU: ",
        "OS_Version: Ubuntu 24.04.5 LTS",
        "GL_VENDOR: Mesa",
        "GL_RENDERER: llvmpipe (LLVM 20.1.2, 256 bits)",
        "GL_VERSION: 4.5 (Core Profile) Mesa 25.2.8-0ubuntu0.24.04.3",
        "GL_SHADING_LANGUAGE_VERSION: 4.50",
    ]
    vk_info = _make_results_info(
        "xemu-0.8.136",
        "Linux_x86_64",
        "vk_Mesa_llvmpipe--gslv_4.50",
        vk_machine_info,
        is_vulkan=True,
    )
    pretty_vk = PrettyMachineInfo.parse(vk_info)
    assert pretty_vk.platform == "Linux_x86_64"
    assert pretty_vk.renderer == "Vulkan"


def test_top_level_index_groups_renderers_under_same_platform(tmp_path: Path) -> None:
    gl_info = _make_results_info(
        "xemu-0.8.136",
        "Linux_x86_64",
        "gl_Mesa_llvmpipe--gslv_4.50",
        [
            "CPU: AMD EPYC 9V74 80-Core Processor",
            "OS_Version: Ubuntu 24.04.4 LTS",
        ],
        is_vulkan=False,
    )
    vk_info = _make_results_info(
        "xemu-0.8.136",
        "Linux_x86_64",
        "vk_Mesa_llvmpipe--gslv_4.50",
        [
            "CPU: ",
            "OS_Version: Ubuntu 24.04.5 LTS",
        ],
        is_vulkan=True,
    )

    results = {
        "run_gl": gl_info,
        "run_vk": vk_info,
    }

    mock_env = MagicMock()
    mock_template = MagicMock()
    mock_template.render.return_value = "<html>mock</html>"
    mock_env.get_template.return_value = mock_template

    writer = PagesWriter(
        results=results,
        env=mock_env,
        output_dir=str(tmp_path),
        result_images_base_url="http://test/results",
        hw_golden_images_base_url="http://test/hw",
        test_source_base_url="http://test/src",
        hw_golden_browser_base_url="http://test/hw_browser",
    )

    writer._write_top_level_index()

    mock_env.get_template.assert_called_with("index.html.j2")
    render_calls = mock_template.render.call_args_list
    assert len(render_calls) == 1
    rendered_groups = render_calls[0].kwargs["emulator_grouped_results"]

    assert "xemu-0.8.136" in rendered_groups
    # There should only be one platform under xemu-0.8.136: "Linux_x86_64"
    assert list(rendered_groups["xemu-0.8.136"].keys()) == ["Linux_x86_64"]
    # Both OpenGL and Vulkan should be nested under Linux_x86_64
    assert "OpenGL" in rendered_groups["xemu-0.8.136"]["Linux_x86_64"]
    assert "Vulkan" in rendered_groups["xemu-0.8.136"]["Linux_x86_64"]


def test_write_run_results_pages_suppresses_deprecated_missing_tests(
    tmp_path: Path,
) -> None:
    run_info = _make_results_info(
        "xemu-0.8.136",
        "Linux_x86_64",
        "gl_Mesa_llvmpipe--gslv_4.50",
        ["CPU: Test"],
    )

    summary = {
        "result_identifier": "xemu-0.8.136:Linux_x86_64:gl_Mesa_llvmpipe:gslv_4.50",
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": [
            "Blend_tests:0_ADD_1",
            "Valid_suite:Valid_test",
        ],
        "tests_without_goldens": [],
        "tests_with_differences": {
            "Blend_tests:0_ADD_1": 10.0,
            "Valid_suite:Other": 5.0,
        },
        "tests_evaluated": [],
    }

    comp = ComparisonInfo.parse(
        run_identifier="xemu-0.8.136/Linux_x86_64/gl_Mesa_llvmpipe--gslv_4.50/Xbox_Hardware",
        summary=summary,
        results=(),
    )
    run_info = ResultsInfo(
        identifier=run_info.identifier,
        machine_info=run_info.machine_info,
        renderer_info=run_info.renderer_info,
        runner_info=run_info.runner_info,
        results=(),
        comparisons=[comp],
    )

    mock_env = MagicMock()
    mock_template = MagicMock()
    mock_template.render.return_value = "<html>mock</html>"
    mock_env.get_template.return_value = mock_template

    golden_config = GoldenConfig(deprecated_tests={"Blend_tests": ["0_ADD_1"]})

    writer = PagesWriter(
        results={str(run_info.identifier): run_info},
        env=mock_env,
        output_dir=str(tmp_path),
        result_images_base_url="http://test/results",
        hw_golden_images_base_url="http://test/hw",
        test_source_base_url="http://test/src",
        hw_golden_browser_base_url="http://test/hw_browser",
        golden_config=golden_config,
    )

    writer._write_run_results_pages(run_info)

    render_calls = mock_template.render.call_args_list
    assert len(render_calls) >= 1
    rendered_comps = render_calls[-1].kwargs["comparisons"]

    hw_comp = rendered_comps["Xbox_Hardware"]
    # "Blend_tests:0_ADD_1" must be suppressed!
    assert "Blend_tests :: 0_ADD_1" not in hw_comp["missing_tests"]
    assert "Valid_suite :: Valid_test" in hw_comp["missing_tests"]
    # difference_count must not count deprecated test differences
    assert hw_comp["difference_count"] == 1


def test_write_comparisons_page_suppresses_deprecated_tests(tmp_path: Path) -> None:
    summary = {
        "result_identifier": "xemu-0.8.136:Linux_x86_64:gl_Mesa_llvmpipe:gslv_4.50",
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": [
            "Blend_tests:0_ADD_1",
            "Valid_suite:Valid_test",
        ],
        "tests_without_goldens": ["Blend_tests:0_ADD_1"],
        "tests_with_differences": {},
        "tests_evaluated": [],
    }

    valid_suite = TestSuiteComparisonInfo(
        suite_name="Valid_suite",
        test_cases=(),
        descriptor=None,
    )
    blend_suite = TestSuiteComparisonInfo(
        suite_name="Blend_tests",
        test_cases=(),
        descriptor=None,
    )

    comp = ComparisonInfo.parse(
        run_identifier="xemu-0.8.136/Linux_x86_64/gl_Mesa_llvmpipe--gslv_4.50/Xbox_Hardware",
        summary=summary,
        results=(valid_suite, blend_suite),
    )

    mock_env = MagicMock()
    mock_template = MagicMock()
    mock_template.render.return_value = "<html>mock</html>"
    mock_env.get_template.return_value = mock_template

    golden_config = GoldenConfig(deprecated_tests={"Blend_tests": ["0_ADD_1"]})

    writer = PagesWriter(
        results={},
        env=mock_env,
        output_dir=str(tmp_path),
        result_images_base_url="http://test/results",
        hw_golden_images_base_url="http://test/hw",
        test_source_base_url="http://test/src",
        hw_golden_browser_base_url="http://test/hw_browser",
        golden_config=golden_config,
    )

    writer._write_comparisons_page(comp, golden_base_url="http://test/hw")

    render_calls = mock_template.render.call_args_list
    assert len(render_calls) == 2
    rendered_results = render_calls[0].kwargs["results"]

    # "Blend_tests" has only deprecated tests, so it must not be in rendered_results
    assert "Blend_tests" not in rendered_results
    assert "Valid_suite" in rendered_results
    # And the per-suite diff page was only rendered for Valid_suite, not Blend_tests
    assert render_calls[1].kwargs["suite_name"] == "Valid_suite"


def test_comparison_scanner_filters_deprecated_tests(tmp_path: Path) -> None:
    comp_dir = (
        tmp_path
        / "compare"
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "gl_Mesa_llvmpipe--gslv_4.50"
        / "Xbox_Hardware"
    )
    suite_dir = comp_dir / "Blend_tests"
    suite_dir.mkdir(parents=True)
    (suite_dir / "0_ADD_1-diff.png").touch()
    (suite_dir / "Valid_test-diff.png").touch()

    summary = {
        "result_identifier": "xemu-0.8.136:Linux_x86_64:gl_Mesa_llvmpipe:gslv_4.50",
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": [
            "Blend_tests:0_ADD_1",
            "Blend_tests:Valid_missing",
        ],
        "tests_without_goldens": [],
        "tests_with_differences": {
            "Blend_tests:0_ADD_1": 15.0,
            "Blend_tests:Valid_test": 5.0,
        },
        "tests_evaluated": ["Blend_tests:Valid_test"],
    }
    (comp_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    golden_config = GoldenConfig(deprecated_tests={"Blend_tests": ["0_ADD_1"]})

    scanner = ComparisonScanner(
        comparison_dir=str(tmp_path / "compare"),
        output_dir=str(tmp_path / "out"),
        base_url="https://example.com",
        results_dir=str(tmp_path / "results"),
        hw_golden_base_url="https://example.com/hw",
        test_suite_descriptors={},
        golden_config=golden_config,
    )

    comp_results = scanner.process()
    assert len(comp_results) == 1
    comps = next(iter(comp_results.values()))
    assert len(comps) == 1
    comp = comps[0]

    # Verify deprecated tests removed from summary in ComparisonInfo
    assert "Blend_tests:0_ADD_1" not in comp.summary["goldens_without_results"]
    assert "Blend_tests:Valid_missing" in comp.summary["goldens_without_results"]
    assert "Blend_tests:0_ADD_1" not in comp.summary["tests_with_differences"]
    assert "Blend_tests:Valid_test" in comp.summary["tests_with_differences"]

    # Verify deprecated diffs excluded from results
    assert len(comp.results) == 1
    blend_results = comp.results[0]
    test_names = [tc.test_name for tc in blend_results.test_cases]
    assert "0_ADD_1" not in test_names
    assert "Valid_test" in test_names


def test_index_source_images_distinguishes_multiple_renderers(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    mesa_dir = (
        results_dir
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "vk_Mesa_llvmpipe"
        / "gslv_4.50"
        / "Point_sprite"
    )
    nvidia_dir = (
        results_dir
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "gl_NVIDIA_Corporation"
        / "gslv_4.00"
        / "Point_sprite"
    )
    mesa_dir.mkdir(parents=True)
    nvidia_dir.mkdir(parents=True)

    mesa_img = mesa_dir / "AlphaTest.png"
    mesa_img.touch()
    nvidia_img = nvidia_dir / "AlphaTest.png"
    nvidia_img.touch()

    indexed = _index_source_images(str(results_dir))

    ident_mesa = SourceTestIdentifier(
        xemu_version="xemu-0.8.136",
        platform_info="Linux_x86_64",
        gl_info="vk_Mesa_llvmpipe--gslv_4.50",
        suite_name="Point_sprite",
        test_name="AlphaTest",
    )
    ident_nvidia = SourceTestIdentifier(
        xemu_version="xemu-0.8.136",
        platform_info="Linux_x86_64",
        gl_info="gl_NVIDIA_Corporation--gslv_4.00",
        suite_name="Point_sprite",
        test_name="AlphaTest",
    )

    assert ident_mesa in indexed
    assert ident_nvidia in indexed
    assert indexed[ident_mesa] == str(mesa_img)
    assert indexed[ident_nvidia] == str(nvidia_img)
    assert len(indexed) == 2


def test_comparison_scanner_links_to_correct_hardware_renderer(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    mesa_results = (
        results_dir
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "vk_Mesa_llvmpipe"
        / "gslv_4.50"
        / "Point_sprite"
    )
    nvidia_results = (
        results_dir
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "gl_NVIDIA_Corporation"
        / "gslv_4.00"
        / "Point_sprite"
    )
    mesa_results.mkdir(parents=True)
    nvidia_results.mkdir(parents=True)
    (mesa_results / "AlphaTest.png").touch()
    (nvidia_results / "AlphaTest.png").touch()

    compare_dir = tmp_path / "compare"
    mesa_comp = (
        compare_dir
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "vk_Mesa_llvmpipe--gslv_4.50"
        / "Xbox_Hardware"
        / "Point_sprite"
    )
    nvidia_comp = (
        compare_dir
        / "xemu-0.8.136"
        / "Linux_x86_64"
        / "gl_NVIDIA_Corporation--gslv_4.00"
        / "Xbox_Hardware"
        / "Point_sprite"
    )
    mesa_comp.mkdir(parents=True)
    nvidia_comp.mkdir(parents=True)
    (mesa_comp / "AlphaTest-diff.png").touch()
    (nvidia_comp / "AlphaTest-diff.png").touch()

    mesa_summary = {
        "result_identifier": "xemu-0.8.136:Linux_x86_64:vk_Mesa_llvmpipe:gslv_4.50",
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": [],
        "tests_without_goldens": [],
        "tests_with_differences": {"Point_sprite:AlphaTest": 1.0},
        "tests_evaluated": ["Point_sprite:AlphaTest"],
    }
    nvidia_summary = {
        "result_identifier": "xemu-0.8.136:Linux_x86_64:gl_NVIDIA_Corporation:gslv_4.00",
        "golden_identifier": "Xbox_Hardware",
        "goldens_without_results": [],
        "tests_without_goldens": [],
        "tests_with_differences": {"Point_sprite:AlphaTest": 2.0},
        "tests_evaluated": ["Point_sprite:AlphaTest"],
    }
    (mesa_comp.parent / "summary.json").write_text(
        json.dumps(mesa_summary), encoding="utf-8"
    )
    (nvidia_comp.parent / "summary.json").write_text(
        json.dumps(nvidia_summary), encoding="utf-8"
    )

    scanner = ComparisonScanner(
        comparison_dir=str(compare_dir),
        output_dir=str(tmp_path / "out"),
        base_url="https://raw.githubusercontent.com/test",
        results_dir=str(results_dir),
        hw_golden_base_url="https://example.com/hw",
        test_suite_descriptors={},
    )

    comp_results = scanner.process()
    assert len(comp_results) == 2

    for comps in comp_results.values():
        assert len(comps) == 1
        comp = comps[0]
        assert len(comp.results) == 1
        suite_res = comp.results[0]
        assert suite_res.suite_name == "Point_sprite"
        assert len(suite_res.test_cases) == 1
        tc = suite_res.test_cases[0]

        if "vk_Mesa_llvmpipe" in comp.identifier.gl_info:
            assert "vk_Mesa_llvmpipe" in tc.source_image_url
            assert "gl_NVIDIA_Corporation" not in tc.source_image_url
        elif "gl_NVIDIA_Corporation" in comp.identifier.gl_info:
            assert "gl_NVIDIA_Corporation" in tc.source_image_url
            assert "vk_Mesa_llvmpipe" not in tc.source_image_url
        else:
            raise AssertionError(f"Unexpected run identifier: {comp.identifier}")
