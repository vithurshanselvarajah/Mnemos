from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONVERT_PY = REPO_ROOT / "mnemos-backend" / "variants" / "rockchip" / "convert.py"


def test_convert_cli_imports():
    """Verify the file at least exists and has the expected structure."""
    assert CONVERT_PY.exists()


def test_convert_cli_source_uses_argparse():
    """The source file imports argparse and uses it."""
    content = CONVERT_PY.read_text()
    assert "import argparse" in content
    assert "ArgumentParser" in content
    assert "--out" in content
    assert "choices=" in content


def test_convert_cli_main_raises_todo():
    """main() should raise NotImplementedError for now."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("convert_test", str(CONVERT_PY))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(NotImplementedError):
        module.main()


def test_convert_cli_module_doc():
    content = CONVERT_PY.read_text()
    assert "RKNN" in content


def test_convert_cli_default_model():
    content = CONVERT_PY.read_text()
    assert "buffalo_s" in content
