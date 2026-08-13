# Testing

The Mnemos test suite is pytest-based, located at the repo root under `tests/`. Both the backend and the frontend have their own test packages, and a single `pytest tests/` runs everything.

- [Running the tests](#running-the-tests)
- [Layout](#layout)
- [The `conftest.py` contract](#the-conftestpy-contract)
- [Backend test patterns](#backend-test-patterns)
- [Frontend test patterns](#frontend-test-patterns)
- [Mocking the inference engine](#mocking-the-inference-engine)
- [Adding a test](#adding-a-test)
- [CI / pre-commit](#ci--pre-commit)

---

## Running the tests

From the repo root:

```bash
python3 -m pytest tests/                     # everything
python3 -m pytest tests/backend/             # only backend
python3 -m pytest tests/frontend/            # only frontend
python3 -m pytest tests/backend/test_persons.py::test_create_person_persists  # one test
python3 -m pytest -x                         # stop on first failure
python3 -m pytest --tb=short                 # shorter tracebacks
```

### Test dependencies

Test-only dependencies (currently just `pytest`) live in `tests/requirements-test.txt` so they stay out of the production images. To set up a fresh dev env:

```bash
python3 -m pip install --upgrade "pip>=25"
python3 -m pip install --only-binary=:all: --prefer-binary \
    -r mnemos-backend/requirements.txt \
    -r mnemos-backend/variants/cpu/requirements.txt \
    -r mnemos-frontend/requirements.txt \
    -r tests/requirements-test.txt
```

The CPU variant (`insightface` + `onnxruntime`) is needed because even though the tests mock the inference engine, `monkeypatch.setattr("insightface.app.FaceAnalysis", ...)` still requires the module to be importable. CI installs the CPU variant for the same reason — never the NVIDIA variant, which would pull in `onnxruntime-gpu` (Linux CUDA libraries).

CI does exactly this in `.github/workflows/ci.yml`. The Dockerfiles only install their respective service `requirements.txt` and the variant that matches the `INSTALL_PROVIDER` build arg — `pytest` and variant inference deps for other architectures are never baked into the runtime images.

You can also use `pytest-watch` for live development:

```bash
ptw tests/backend/ -- -x
```

Expected runtime: < 10 seconds on a modern laptop for the full suite.

## Layout

```
tests/
├── conftest.py                       # shared fixtures (env setup, sys.path swap)
├── test_version.py                   # smoke test
├── backend/
│   ├── test_auth.py
│   ├── test_keys.py
│   ├── test_persons.py
│   ├── test_security.py
│   └── test_nvidia_preflight.py
└── frontend/
    ├── test_auth.py
    ├── test_passwords.py
    └── test_settings.py
```

Each per-service test directory is a Python package (`__init__.py` present). The shared `conftest.py` lives at the top.

## The `conftest.py` contract

The backend and the frontend each have their own `app.*` package. They cannot both be on `sys.path` at the same time — Python would resolve `app` to whichever was added first, and the other would shadow it. The conftest handles this by swapping `sys.path` per test.

### Fixtures

| Fixture | Purpose |
| --- | --- |
| `tmp_root` | A `tempfile.mkdtemp()` directory; cleaned up on teardown. |
| `chdir_backend` / `chdir_frontend` | `os.chdir` into the right service root. |
| `backend_env` / `frontend_env` | Sets the right `MNEMOS_*` / `MNEMOS_FE_*` env vars to point at the temp dir. Restored on teardown. |
| `backend_imports` / `frontend_imports` | Combines the env + chdir + a `sys.path` swap that evicts the other service's `app.*` modules. This is the one most tests should use. |
| `unique_name` | A random string for tests that create persons. |

### Why the env vars must be set before the import

`Settings()` reads env vars at construction time. If you do `from app.core.config import settings` first, the `Settings()` is already constructed with the defaults. The conftest sets env first, then yields, and on teardown restores. The test body can then call `set_settings(Settings(...))` to inject overrides.

### SQLModel metadata reset

The conftest swaps `SQLModel.metadata` to a fresh `MetaData()` on entry and restores the old one on exit. This stops test classes from accumulating duplicate tables across tests, which would otherwise fire `SAWarning: This declarative base already contains a class with the same class name…`.

## Backend test patterns

### Smoke-testing an endpoint

```python
import pytest

@pytest.fixture
def api_client(backend_imports):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()

    app = create_app()
    client = TestClient(app)
    pair = client.post(
        "/api/v1/system/pair",
        json={"master_key": ensure_master_key(), "name": "pytest"},
    )
    assert pair.status_code == 200, pair.text
    api_key = pair.json()["raw_key"]
    return client, api_key


def test_my_endpoint(api_client):
    client, key = api_client
    r = client.post("/api/v1/…", headers={"X-API-Key": key}, json={…})
    assert r.status_code == 200, r.text
    assert r.json() == …
```

The fixture handles the full bootstrap: settings, DB, app, master key, paired API key. Most backend tests look exactly like this.

### Pure unit tests (no DB)

If the test doesn't need a running app, you can still use `backend_imports` for the `app.*` imports, but skip the `api_client` fixture:

```python
def test_preflight_provider_nvidia_no_libcuda(backend_imports, monkeypatch):
    from app.providers import nvidia as nvidia_mod
    from app.services import model_manifest
    # …
```

`backend_imports` is what sets up `sys.path` and the env. The body can then mock whatever it needs.

## Frontend test patterns

The frontend has the same shape: a `frontend_imports` fixture plus per-test `TestClient` setups. The most common pattern is testing a Jinja-rendered page:

```python
def test_login_renders_form(frontend_imports):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.get("/login")
    assert r.status_code == 200
    assert "Username" in r.text
```

## Mocking the inference engine

`tests/backend/test_nvidia_preflight.py` is the canonical example. The pattern:

```python
from unittest import mock

def test_healthz_includes_nvidia(backend_imports, monkeypatch):
    from app.providers import nvidia as nvidia_mod
    from app.services import engine as engine_mod

    monkeypatch.setattr(nvidia_mod, "detect_cuda_provider", lambda: {
        "onnxruntime_available": True,
        "cuda_available": True,
        "device_count": 1,
        "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "active_providers": ["CUDAExecutionProvider"],
        "last_error": None,
    })
    monkeypatch.setattr(engine_mod, "_load_provider", lambda *_a, **_kw: mock.MagicMock(
        is_loaded=lambda: True,
        active_providers=["CUDAExecutionProvider"],
        last_error=None,
    ))
    # … call the endpoint, assert the response …
```

The two important tricks:

1. **Mock `_load_provider`**, not the inner engine class. The factory in `engine.py` calls `_load_provider(name, model_name, det_size)` — patching that one function is enough.
2. **Always reset the singleton** with `engine_mod.InsightFaceEngine.reset()` between tests. Otherwise one test's mock leaks into the next.

## Adding a test

1. Pick the right directory: `tests/backend/` or `tests/frontend/`.
2. Use `backend_imports` or `frontend_imports` for any test that imports from `app.*`.
3. Follow the `api_client` pattern for HTTP tests, or the bare `monkeypatch` pattern for unit tests.
4. Run the test, then run the full suite, before opening a PR.

If your test creates persons or faces, use the `unique_name` fixture to avoid name collisions.

## CI / pre-commit

The repository has a GitHub Actions workflow that runs `pytest` and `ruff check` on every PR. Before pushing:

```bash
python3 -m pytest tests/
python3 -m ruff check .
python3 -m ruff format --check .
```

Ruff is configured via `ruff.toml` at the repo root. It catches the obvious (unused imports, unsorted imports, pyupgrade hints, bugbear) and leaves the rest to author discretion. The test files are slightly more permissive (`B011`, `SIM117`, `SIM105` are not enforced) because pytest fixtures naturally produce a lot of `try/except/raise`.

---

## For developers

### Why a single top-level conftest

Both services have their own `app.*` package, and only one can be importable at a time. The conftest lives at the top and uses a context manager to swap `sys.path` per test. The alternative (one conftest per service) was tried and abandoned because pytest doesn't isolate conftest state across directories by default.

### Why pytest and not unittest

pytest's fixture system is much cleaner for this style of test (lots of setup, lots of teardown, lots of mocks). unittest's `setUp/tearDown` is verbose by comparison, and the `mock.patch` context manager is awkward to use with class-based tests. The trade-off is that pytest has more magic, but for a project of this size the magic is worth it.

### How to debug a failing test

```bash
python3 -m pytest tests/backend/test_persons.py::test_create_duplicate_name_rejected -x --tb=long -s
```

- `-x` — stop on first failure
- `--tb=long` — full traceback
- `-s` — don't capture stdout/stderr, so `print()` debugging works

If the failure is in conftest setup, the same flags will show you the conftest traceback. If the failure is "module not found" on import, the `sys.path` swap is the first place to look.
