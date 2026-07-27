from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_backend_requirements_exists():
    p = REPO_ROOT / "mnemos-backend" / "requirements.txt"
    assert p.is_file()


def test_backend_requirements_includes_core_packages():
    txt = (REPO_ROOT / "mnemos-backend" / "requirements.txt").read_text()
    assert "fastapi" in txt
    assert "sqlmodel" in txt
    assert "psycopg" in txt or "psycopg[binary]" in txt
    assert "uvicorn" in txt or "hypercorn" in txt
    assert "opencv" in txt or "opencv-python" in txt


def test_backend_requirements_uses_pinned_versions():
    """Production requirements should use pinned versions (== or ~=)."""
    txt = (REPO_ROOT / "mnemos-backend" / "requirements.txt").read_text()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line or "~=" in line, f"unpinned: {line}"


def test_frontend_requirements_exists():
    p = REPO_ROOT / "mnemos-frontend" / "requirements.txt"
    assert p.is_file()


def test_frontend_requirements_includes_core():
    txt = (REPO_ROOT / "mnemos-frontend" / "requirements.txt").read_text()
    assert "fastapi" in txt
    assert "sqlmodel" in txt
    assert "uvicorn" in txt or "hypercorn" in txt
    assert "httpx" in txt
    assert "websockets" in txt
    assert "argon2-cffi" in txt


def test_frontend_requirements_uses_pinned_versions():
    txt = (REPO_ROOT / "mnemos-frontend" / "requirements.txt").read_text()
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line or "~=" in line, f"unpinned: {line}"


def test_cpu_variant_requirements_pins_onnxruntime():
    txt = (REPO_ROOT / "mnemos-backend" / "variants" / "cpu" / "requirements.txt").read_text()
    assert "onnxruntime==" in txt
    assert "insightface" in txt


def test_nvidia_variant_requirements_pins_onnxruntime_gpu():
    txt = (REPO_ROOT / "mnemos-backend" / "variants" / "nvidia" / "requirements.txt").read_text()
    assert "onnxruntime-gpu==" in txt


def test_rockchip_variant_requirements_pins_numpy():
    txt = (REPO_ROOT / "mnemos-backend" / "variants" / "rockchip" / "requirements.txt").read_text()
    assert "numpy==" in txt


def test_cpu_and_nvidia_use_same_insightface_version():
    cpu = (REPO_ROOT / "mnemos-backend" / "variants" / "cpu" / "requirements.txt").read_text()
    nvidia = (REPO_ROOT / "mnemos-backend" / "variants" / "nvidia" / "requirements.txt").read_text()
    cpu_v = next(line for line in cpu.splitlines() if "insightface" in line)
    nvidia_v = next(line for line in nvidia.splitlines() if "insightface" in line)
    assert cpu_v == nvidia_v


def test_cpu_and_nvidia_use_same_onnxruntime_version():
    cpu = (REPO_ROOT / "mnemos-backend" / "variants" / "cpu" / "requirements.txt").read_text()
    nvidia = (REPO_ROOT / "mnemos-backend" / "variants" / "nvidia" / "requirements.txt").read_text()
    cpu_v = next(line for line in cpu.splitlines() if line.startswith("onnxruntime=="))
    nvidia_v = next(line for line in nvidia.splitlines() if line.startswith("onnxruntime-gpu=="))
    cpu_ver = cpu_v.split("==")[1]
    nvidia_ver = nvidia_v.split("==")[1]
    assert cpu_ver == nvidia_ver
