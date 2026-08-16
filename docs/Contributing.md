# Contributing

Thanks for wanting to make Mnemos better. This page covers the workflow, code style, and PR conventions.

- [Code of conduct](#code-of-conduct)
- [Filing issues](#filing-issues)
- [Proposing changes](#proposing-changes)
- [Development setup](#development-setup)
- [Code style](#code-style)
- [Testing](#testing)
- [Database migrations](#database-migrations)
- [Commit messages](#commit-messages)
- [Pull request process](#pull-request-process)
- [Release process](#release-process)

---

## Code of conduct

This project follows the standard GitHub community guidelines: be respectful, assume good faith, and help others learn. There's no separate CODE_OF_CONDUCT.md; the GitHub Terms of Service apply.

## Filing issues

- **Bugs** — use the bug report template. Include the version (`curl http://localhost:8000/healthz | jq .version`), the provider, and the full log line that triggered the bug.
- **Feature requests** — open a discussion first if the change is significant. Small changes (a new env var, a new endpoint) can go straight to a PR.
- **Security issues** — see [Security](https://github.com/vithurshanselvarajah/Mnemos/wiki/Security#reporting-a-vulnerability). Do not file a public issue.

## Proposing changes

For non-trivial changes, open an issue (or a GitHub Discussion) describing:

1. What you want to do and why
2. The user-facing impact (new endpoint, new env var, breaking change?)
3. Any alternative approaches you considered

A short design doc or even a paragraph of context goes a long way. PRs that show up without context often end up in a back-and-forth that would have been a single round-trip if we'd talked first.

## Development setup

```bash
git clone https://github.com/vithurshanselvarajah/Mnemos.git
cd Mnemos
bin/mnemos up                 # build + start the dev stack
bin/mnemos logs               # tail all logs
```

The dev stack builds images from your local source via `docker-compose.dev.yml`. Changes to `mnemos-backend/app/` are live-reloaded by uvicorn (if `MNEMOS_RELOAD=1` is set in your `.env`); changes to `mnemos-frontend/app/` are likewise live-reloaded. Changes to `requirements.txt` or the Dockerfile require a `bin/mnemos up --build`.

For non-Docker work (e.g. you want to run a single test in a venv):

```bash
cd mnemos-backend
python3 -m venv .venv
. .venv/bin/activate
pip install -e . -r requirements.txt -r ../tests/dev-requirements.txt  # if you have a dev reqs file
pytest ../tests/backend/
```

The full test suite is `< 10s` on a modern laptop. See [Testing](https://github.com/vithurshanselvarajah/Mnemos/wiki/Testing) for the layout and fixtures.

## Code style

- Python 3.14 syntax (PEP 604 unions, `type | None`, modern generics).
- `ruff` for everything else. Run `ruff check .` and `ruff format .` before committing.
- The ruff config is in `ruff.toml` at the repo root. It catches the obvious and leaves the rest to author discretion. Test files are slightly more permissive.
- Prefer pure functions over methods. Prefer composition over inheritance. Prefer explicit over clever.
- No comments unless the code is non-obvious. The git log is for "why we did this"; the code is for "what this does." If you find yourself writing a long comment, ask whether the code can be clearer instead.

## Testing

Every PR should include tests for the new behaviour. See [Testing](https://github.com/vithurshanselvarajah/Mnemos/wiki/Testing) for the patterns. The CI workflow runs:

- `pytest tests/` — full suite must pass
- `ruff check .` — no lint errors
- `ruff format --check .` — code is formatted

If you're fixing a bug, add a regression test that fails on `main` and passes on your branch. If you're adding an endpoint, add a happy-path test and at least one failure-mode test.

## Database migrations

Both `mnemos-backend` and `mnemos-frontend` use the same lightweight migration runner — no Alembic, no `alembic_version` table out of the box. Migrations are versioned files under `app/db/migrations/`, auto-discovered on startup, and tracked in a `schema_version` table inside the same SQLite database.

### How it works

```
mnemos-backend/app/db/migrations/
├── __init__.py
├── runner.py          # discovers + applies pending migrations
├── 0001_pairing_key.py # each migration is one ALTER TABLE (or similar)
├── 0002_...
```

On every `init_db()` call, the runner:

1. Creates the `schema_version(version, name, applied_at)` table if it doesn't exist.
2. Reads `MAX(version)` of already-applied migrations.
3. Runs every migration file whose `VERSION` is greater than the highest applied version, in order.
4. Records each successful upgrade into `schema_version`.

A migration's `upgrade()` is also wrapped in a `try/except` that swallows `duplicate column name` and `already exists` errors. This makes the runner robust against a fresh V2 install where `SQLModel.metadata.create_all()` has already created the full V2 schema — the ALTER TABLE is a no-op, but the version row is still recorded so a later V1→V2 upgrade of a V1 database correctly picks up the migration.

### Adding a new migration

1. Pick the next integer version. Check the existing files in `app/db/migrations/`.
2. Create `app/db/migrations/NNNN_short_name.py` with this shape:

    ```python
    from sqlalchemy import text

    VERSION = 2
    NAME = "add persons.notes column"


    def upgrade(conn) -> None:
        conn.execute(text("ALTER TABLE persons ADD COLUMN notes TEXT"))
    ```

3. Update the matching model in `app/models/entities.py` so a fresh `create_all()` also produces the new column. The migration is the V1→V2 upgrade path; the model change is the V2-fresh-install path.
4. Add a regression test in `tests/backend/test_db_session.py` (or `tests/frontend/test_frontend_db.py`) that:
   - Creates a V1-shaped DB.
   - Calls `init_db()`.
   - Asserts the new column exists and existing rows still read back correctly.
   - Asserts `schema_version` contains your new version.
5. Run the full suite: `pytest tests/`.

### Conventions

- Migration files are matched by the `NNN_` prefix. Anything that doesn't start with four digits followed by an underscore is ignored (so `runner.py` and `__init__.py` won't be treated as migrations).
- Versions are monotonically increasing integers. Don't reuse a version.
- Keep migrations small and idempotent. If a migration needs data backfill, do it in the same `upgrade()` and make the SQL robust to "already done" (e.g. `WHERE NOT EXISTS`).
- Never modify a migration after it has been merged to `main`. If you need to change behaviour, add a new migration.

### Why no Alembic?

Each service has a single SQLite database with a small, stable schema. Alembic is overkill for this scale, and adopting it would have meant a bigger refactor (new dependency, new `env.py`, new CI wiring) for no real benefit. The runner above is ~80 lines and does exactly what Mnemos needs: track applied versions, apply pending ones, be safe to re-run. If the project ever grows to a second engineer + a Postgres + a more complex schema, the path to Alembic is straightforward — port the existing `0001_*` migration to an Alembic revision, set `alembic_version` to `1`, and retire the runner.

## Commit messages

Imperative, present tense, no period, ≤ 72 chars on the subject line. The body wraps at 72.

```
add /api/v1/persons/{id}/crops endpoint

Lets clients list the assigned crops for a person without having
to hit /api/v1/faces/unassigned and filter client-side.

Refs #42
```

If the change is a single topic, a one-liner is fine:

```
fix: reindex crash on empty gallery
```

Squash your commits before merging. The squash commit message becomes the merge commit message.

## Pull request process

1. Open a PR from a feature branch. Branch names are `feat/…`, `fix/…`, `chore/…`, `docs/…`.
2. Fill in the PR template. If there's no template, write a paragraph: what changed, why, anything reviewers should pay attention to.
3. CI must be green before review.
4. Reviewers will be assigned automatically. Expect at least one approval before merge.
5. Squash and merge. The squash commit lands on `main`.
6. The release process below picks it up from there.

## Release process

Releases are tagged manually by the maintainer. The flow is:

1. `main` accumulates PRs.
2. When ready to release, the maintainer runs the release script (or hand-cuts a tag).
3. The CI workflow builds and pushes the three images (`mnemos-backend:{tag}-{cpu,nvidia,rockchip}`, `mnemos-frontend:{tag}`) to GHCR.
4. The release is published with the changelog extracted from commit messages.
5. The `VERSION` file at the repo root is bumped to the new version.

The release cadence is "when something's worth releasing" — there's no fixed schedule. Bug fixes can be released as patch versions; new endpoints or providers are minor versions; breaking changes are major versions.

---

## For developers

### Repo layout

```
Mnemos/
├── docs/                    # this wiki (syncs to GitHub wiki)
├── mnemos-backend/          # Python FastAPI backend
├── mnemos-frontend/         # Python FastAPI frontend
├── pgvector-init/           # SQL init for the pgvector service
├── tests/                   # shared pytest suite
├── bruno/                   # Bruno API collection (hand-test the API)
├── bin/mnemos               # dev wrapper
├── docker-compose.yml       # production compose
├── docker-compose.dev.yml   # dev compose
├── manifest.json            # model manifest (mirrored at MNEMOS_MANIFEST_URL)
├── changelog.md
├── LICENSE
├── pytest.ini
├── ruff.toml
└── VERSION
```

### Why monorepo, not polyrepo

The backend and frontend are tightly coupled (the frontend's API proxy must match the backend's API shape). Polyrepo would mean every API change is two PRs, two CI runs, two releases. Monorepo means one PR, one CI run, one release. The trade-off is that the repo is bigger; for a project this size that's not a problem.

### Where the docs live

`docs/` is the source of truth. Every page is flat (no subfolders — the GitHub wiki mirrors the layout). Cross-links are relative paths; see the [Home](https://github.com/vithurshanselvarajah/Mnemos/wiki/Home) page for the link map. To propose a docs change, edit the file in `docs/` and open a PR; the wiki re-syncs on merge to `main`.
