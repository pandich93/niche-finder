# Contributing to niche-finder

Thanks for considering a contribution. This project is a small, self-hosted
tool, so the bar is low and the process is simple.

## Ways to contribute

- **Bug reports** — open an issue with what you ran, what you expected, and
  what happened. `docker compose run --rm mcp python cli.py doctor` (or
  `make doctor`) is usually the first thing worth including — it checks the
  key, network, and database in one shot.
- **Bug fixes / small improvements** — open a PR directly.
- **New MCP tools / API endpoints / dashboard screens** — please open an
  issue first to agree on the shape before writing code, so you don't end up
  reworking it.
- **Documentation** — typos, unclear steps, outdated commands: PRs welcome,
  no need to ask first.

## Getting set up

```bash
git clone https://github.com/pandich93/niche-finder.git
cd niche-finder
cp .env.example .env          # YOUTUBE_API_KEY is optional for local dev
docker compose build
docker compose up -d postgres worker
make doctor
```

Or without Docker — see
[backend/README.md#running-without-docker](backend/README.md#running-without-docker).

## Running the tests

```bash
make up-db        # start just Postgres
make test         # smoke tests inside the image, no YouTube key or network needed
# or, without Docker:
make local-install
make local-test
```

`make test` / `make local-test` should print `17/17 passed`. CI runs the
same suite (see `.github/workflows/ci.yml`) plus a `docker compose build`
check on every push and pull request — both must be green before a PR is
merged.

If you add a new use case, add a smoke test for it in
`backend/tests/test_smoke.py` alongside the existing ones; there's no
mocking layer, tests run against a real (throwaway-schema) Postgres.

## Code layout

The backend follows a DDD-ish layering — see
[backend/README.md#structure](backend/README.md#structure) for the full
tree. In short:

- `domain/` — pure formulas and parsing, no I/O, no external dependencies.
- `infrastructure/` — adapters to Postgres, the YouTube API, and the local
  embeddings model.
- `application/` — use cases that orchestrate domain + infrastructure.
- `interfaces/` — thin entry points (MCP server, HTTP API, CLI, worker).

`server.py`, `api.py`, `cli.py`, and `worker.py` at the top of `backend/`
are shims that just import from `interfaces/` — don't add logic there.
`backend/_legacy_flat_modules/` is a frozen reference of the pre-DDD code;
nothing imports it, don't add to it.

The frontend (`frontend/`) is plain ES modules with no build step and no
framework — keep it that way. New screens follow the existing pattern in
`app.js` (hash routing) and `ui.js` (shared components/formatters).

## Style

- No linter is enforced yet; match the style of the surrounding code
  (naming, docstrings, formatting).
- Keep entry-point shims thin — real logic belongs in `domain/`,
  `infrastructure/`, or `application/`.
- Prefer adding a smoke test over adding a mock.

## Submitting a PR

1. Fork the repo and create a branch off `main`.
2. Make your change, keeping it focused — unrelated cleanup makes review
   harder.
3. Run `make test` (or `make local-test`) and confirm `docker compose build`
   still works if you touched `backend/requirements.txt` or the Dockerfile.
4. Open a PR describing what changed and why. Link the issue it addresses,
   if any.
5. CI must pass (smoke tests + Docker build) before merge.

By contributing, you agree your contribution is licensed under this
project's [MIT License](LICENSE).
