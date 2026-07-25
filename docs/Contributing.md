# Contributing

Thanks for wanting to make Mnemos better. This page covers the workflow, code style, and PR conventions.

- [Code of conduct](#code-of-conduct)
- [Filing issues](#filing-issues)
- [Proposing changes](#proposing-changes)
- [Development setup](#development-setup)
- [Code style](#code-style)
- [Testing](#testing)
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
