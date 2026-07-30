# Changelog

All notable changes to Alap-Alap are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Re-audited README, contribution guidance, and GitHub templates against the current codebase, documenting setup limitations, CLI options, single/batch result shapes, REST contracts and operational caveats, submit-triggered job-retention cleanup, result-output path behavior, configuration, security defaults, browser pooling, test workflow, and repository layout.
- Pinned the development and pre-commit Black formatter to the same version so local hooks and CI produce identical output.
- Removed static test, coverage, and benchmark claims from user-facing documentation when they were not tied to a reproducible environment.
- Expanded `.gitignore` for environment secrets, packaging output, parallel coverage, quality-tool caches, browser-test reports, atomic database temp files, logs, and local tool state.
- Documented which runtime files are generated locally and intentionally excluded from commits.

## [1.2.0] - 2026-07-30

### Added

- A REST API browser pool. Each worker owns one browser on its own thread and can reuse it across requests.
- A bounded asynchronous job queue with `POST /jobs`, `GET /jobs/<id>`, and `GET /jobs`.
- Pool state in `/health`, `/stats`, and job-list responses.
- Token acquisition timestamps and freshness helpers (`token_age`, `token_expires_in`, and `token_is_fresh`) in the sitekey database and API/CLI output.
- Real-browser integration coverage for browser reuse and warm solves.
- Pre-commit hooks aligned with lint, format, hygiene, secret, and unit-test checks.
- Pool and retention settings: `api.POOL_ENABLED`, `api.POOL_MAX_SOLVES_PER_BROWSER`, `api.QUEUE_MAX_SIZE`, `api.JOB_TTL_S`, and `api.JOB_MAX_RETAINED`.

### Changed

- `api.MAX_CONCURRENT_SOLVES` now controls both pool worker count and concurrent solves.
- `POST /solve` uses the queue internally. If its wait budget expires while work continues, it returns `202` with a job id and polling URL.
- Queue saturation returns `503` instead of allowing an unbounded backlog.
- Browsers relaunch when a job changes proxy, can recycle after a configured number of solves, and can return to launch-per-request behavior when pooling is disabled.
- API responses can withhold solved tokens with `api.RETURN_TOKENS=false`.
- `create_app()` accepts an injected `SolverPool`, allowing tests and embedders to provide their own browser factory.

### Fixed

- Browser recycle counters are incremented correctly, so `api.POOL_MAX_SOLVES_PER_BROWSER` now takes effect.
- Polling the same completed job repeatedly no longer records duplicate database solves.
- Browser crashes mark the affected job as an error and do not prevent the pool from serving subsequent jobs.

## [1.1.0] - 2026-07-30

### Added

- Working proxy support across `requests`, Camoufox, the CLI, Python API, REST API, and parallel batches. Supported schemes are HTTP, HTTPS, SOCKS4, SOCKS5, and SOCKS5H.
- `src/proxy.py`, including normalized proxy representations, masked logging, and round-robin proxy pools.
- `src/errors.py` with a shared exception hierarchy.
- `src/models.py` with stable result models and strict Pydantic request validation.
- `src/security.py` with URL validation, API-key comparison, and per-client rate limiting.
- Batch solving through `AlapAlap.solve_many()`, `solve_batch()`, and the `batch` CLI command.
- Optional YAML configuration and `ALAP_<SECTION>_<FIELD>` environment overrides.
- CLI commands `config`, `setup`, and sitekey database pruning/export options.
- API-key authentication through `X-API-Key` or a Bearer token.
- SSRF protection for REST endpoints that accept caller-controlled URLs.
- HTTP retry/backoff, jitter, response-size limits, and wall-clock solve deadlines.
- Detection method reporting, additional sitekey patterns, same-origin script scanning, and prioritized JavaScript-bundle analysis.
- Atomic, thread-safe sitekey database writes, corruption quarantine, querying, statistics, pruning, and CSV/JSON/Markdown exports.
- Structured JSON-file logging and independently configurable console/file levels.
- Browser-free unit coverage plus opt-in real-browser integration tests using controlled testing sitekeys.

### Changed

- The API binds to `127.0.0.1` by default instead of all interfaces.
- API authentication remains optional for loopback development, but off-loopback open bindings emit a warning.
- Tokens stored on disk are redacted by default; in-memory solve results remain complete.
- A previously successful sitekey is not demoted after one failed solve.
- Browser dependencies are installed only by commands that need them; importing the package or asking for help does not trigger installation.
- The CLI moved to `src/cli.py`; root `main.py` remains a thin compatibility shim.
- Integration tests are excluded by default and selected with `pytest -m integration`.
- Pyright runs in basic mode, and CI covers `main.py`, builds distributions, and verifies installed entry points.
- Packaging now includes an explicit build backend, package discovery, runtime dependencies, and the `alap-alap` console script.

### Fixed

- CLI, library, and API proxy arguments are now applied instead of being silently ignored.
- URL normalization preserves query strings and fragments rather than appending `/` to the raw string.
- Visible solving prefers the Cloudflare iframe over unrelated page iframes.
- Mouse paths and polling loops have hard bounds to prevent hangs.
- Non-positive retry counts no longer leave a missing result or crash the CLI.
- `sitekeys search <query>` accepts the documented positional query while retaining `--query` compatibility.
- `AlapAlap` can start lazily without a context manager and exposes idempotent cleanup.
- Concurrent database writes no longer risk truncating or corrupting JSON.
- Windows redirected output is forced to UTF-8-safe behavior.
- CI generates the coverage artifact it uploads.

### Removed

- A stale, source-free `src/alap_alap/` bytecode directory.

## [1.0.0]

### Added

- Initial sitekey detection, Camoufox solving, Flask API, CLI, logging, and sitekey persistence.

## Upgrade notes

### Upgrading to 1.2.0

- `POST /solve` may now return `202` when its synchronous wait budget expires. Follow `poll` or the `Location` header to retrieve the result.
- API browser work is owned by `SolverPool`. Tests that previously patched `src.core.AlapAlap` should inject a pool or browser factory instead.
- Pool workers retain browsers. Set `ALAP_API_POOL_ENABLED=false` to restore launch-per-request behavior, or configure `ALAP_API_POOL_MAX_SOLVES_PER_BROWSER` to recycle browsers periodically.

### Upgrading to 1.1.0

- Invalid proxy strings now raise `ProxyError` rather than being ignored.
- The API defaults to `127.0.0.1`. Pass `--host 0.0.0.0` only for an authorized deployment and set `ALAP_API_KEY` first.
- Stored tokens are redacted by default. Set `ALAP_STORAGE_REDACT_STORED_TOKENS=false` only when the local storage risk is understood.
- Integration tests are opt-in with `pytest -m integration`.

## Support

Report bugs and request features through [GitHub Issues](https://github.com/idugeni/alap-alap/issues).
