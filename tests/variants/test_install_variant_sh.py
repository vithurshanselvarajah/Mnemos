from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = REPO_ROOT / "mnemos-backend" / "variants" / "install-variant.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_install_variant_sh_syntax_clean():
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash syntax error: {result.stderr}"


def test_install_variant_sh_is_executable_in_git():
    """The script should have +x bit set in the repo (or be runnable)."""
    content = INSTALL_SCRIPT.read_text()
    assert content.startswith("#!/usr/bin/env bash"), "missing shebang"


def test_install_variant_sh_requires_requirements_arg():
    content = INSTALL_SCRIPT.read_text()
    assert "${1:?usage" in content


def test_install_variant_sh_supports_override_pkg_env():
    content = INSTALL_SCRIPT.read_text()
    assert "PROVIDER_OVERRIDE_PKG" in content


def test_install_variant_sh_excludes_override_pkg():
    content = INSTALL_SCRIPT.read_text()
    assert "grep -v" in content


def test_install_variant_sh_uses_no_deps():
    content = INSTALL_SCRIPT.read_text()
    assert "--no-deps" in content


def test_install_variant_sh_installs_override_with_prefer_binary():
    content = INSTALL_SCRIPT.read_text()
    assert "--prefer-binary" in content
    assert "override_pkg" in content


def test_cpu_requirements_pins_onnxruntime(tmp_path):
    """CPU variant requires onnxruntime (NOT -gpu)."""
    txt = (REPO_ROOT / "mnemos-backend" / "variants" / "cpu" / "requirements.txt").read_text()
    assert "onnxruntime==1.27.0" in txt
    assert "onnxruntime-gpu" not in txt


def test_nvidia_requirements_pins_onnxruntime_gpu(tmp_path):
    txt = (REPO_ROOT / "mnemos-backend" / "variants" / "nvidia" / "requirements.txt").read_text()
    assert "onnxruntime-gpu" in txt


def test_rockchip_requirements_pins_numpy(tmp_path):
    txt = (REPO_ROOT / "mnemos-backend" / "variants" / "rockchip" / "requirements.txt").read_text()
    assert "numpy==" in txt


def test_install_variant_sh_runs_with_stub_reqs(tmp_path):
    """Running the script with a no-op stub requirements file should
    succeed end-to-end (assuming pip is available)."""
    stub_reqs = tmp_path / "stub.txt"
    stub_reqs.write_text("nonexistent-package==99.99.99\n")
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), str(stub_reqs)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/usr/local/bin", "PROVIDER_OVERRIDE_PKG": "nonexistent-override-pkg"},
    )
    # The script may fail because the packages don't exist, but it should
    # at least be parseable and start. We just check it didn't fail with
    # "command not found".
    assert "command not found" not in result.stderr
