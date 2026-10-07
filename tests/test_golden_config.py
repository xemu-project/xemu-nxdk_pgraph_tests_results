from __future__ import annotations

import json
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

from xemu_pgraph_ci_tools.golden_config import (
    DEFAULT_HW_GOLDEN_CONFIG_URL,  # noqa: F401
    GoldenConfig,
    load_golden_config,
)


def test_golden_config_is_deprecated() -> None:
    config = GoldenConfig(
        deprecated_tests={
            "Blend_tests": ["0_ADD_1", "0_MAX_1"],
            "Texture cubemap": ["Cubemap"],
        }
    )

    assert config.has_deprecated_tests is True
    assert config.is_deprecated("Blend_tests", "0_ADD_1") is True
    assert config.is_deprecated("Blend tests", "0_ADD_1") is True
    assert config.is_deprecated("Blend_tests", "0_MAX_1") is True
    assert config.is_deprecated("Texture_cubemap", "Cubemap") is True
    assert config.is_deprecated("Texture cubemap", "Cubemap") is True

    # Non-deprecated tests
    assert config.is_deprecated("Blend_tests", "OtherTest") is False
    assert config.is_deprecated("OtherSuite", "0_ADD_1") is False


def test_golden_config_is_deprecated_fq() -> None:
    config = GoldenConfig(
        deprecated_tests={
            "Blend_tests": ["0_ADD_1"],
        }
    )

    assert config.is_deprecated_fq("Blend_tests:0_ADD_1") is True
    assert config.is_deprecated_fq("Blend tests:0_ADD_1") is True
    assert config.is_deprecated_fq("Blend_tests::0_ADD_1") is True
    assert config.is_deprecated_fq("Blend_tests :: 0_ADD_1") is True
    assert config.is_deprecated_fq("Blend_tests:NonExistent") is False
    assert config.is_deprecated_fq("OtherSuite:0_ADD_1") is False


def test_load_golden_config_from_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    data = {
        "deprecated_tests": {
            "Texture_render_target": ["TexFmt_A8"],
        },
        "version": 1,
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_golden_config(config_path=str(config_file))
    assert loaded.has_deprecated_tests is True
    assert loaded.is_deprecated("Texture_render_target", "TexFmt_A8") is True
    assert loaded.is_deprecated("Texture_render_target", "Other") is False


def test_load_golden_config_from_golden_dir(tmp_path: Path) -> None:
    golden_dir = tmp_path / "golden" / "results"
    golden_dir.mkdir(parents=True)
    config_file = tmp_path / "golden" / "config.json"
    data = {
        "deprecated_tests": {
            "ZPass_pixel_count": ["ZPassPointSizeVS-0x01F9"],
        }
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_golden_config(golden_dir=str(golden_dir), config_url=None)
    assert loaded.is_deprecated("ZPass_pixel_count", "ZPassPointSizeVS-0x01F9") is True


def test_load_golden_config_from_cache_path(tmp_path: Path) -> None:
    cache_golden_dir = tmp_path / "cache" / "nxdk_pgraph_tests_golden_results"
    cache_golden_dir.mkdir(parents=True)
    config_file = cache_golden_dir / "config.json"
    data = {
        "deprecated_tests": {
            "ZPass_pixel_count": ["ZPassPointSizeVS-0x0200"],
        }
    }
    config_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_golden_config(cache_path=str(tmp_path / "cache"), config_url=None)
    assert loaded.is_deprecated("ZPass_pixel_count", "ZPassPointSizeVS-0x0200") is True


def test_load_golden_config_fallback_url() -> None:
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps(
        {
            "deprecated_tests": {"Blend_tests": ["0_SUB_1"]},
            "version": 1,
        }
    ).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_response):
        loaded = load_golden_config(
            config_path="/non/existent/path.json",
            golden_dir="/non/existent/dir",
            cache_path="/non/existent/cache",
            config_url="https://example.com/config.json",
        )
        assert loaded.is_deprecated("Blend_tests", "0_SUB_1") is True


def test_load_golden_config_failure_graceful() -> None:
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        loaded = load_golden_config(
            config_path="/non/existent/path.json",
            golden_dir="/non/existent/dir",
            cache_path="/non/existent/cache",
            config_url="https://example.com/config.json",
        )
        assert loaded.has_deprecated_tests is False
