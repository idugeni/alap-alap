<div align="center">

# Alap-Alap

Cloudflare Turnstile sitekey detector and solver built with Camoufox.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/idugeni/alap-alap/actions/workflows/ci.yml/badge.svg)](https://github.com/idugeni/alap-alap/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Installation](#installation) · [CLI](#command-line-interface) · [Python API](#python-api) · [REST API](#rest-api) · [Configuration](#configuration) · [Development](#development)

</div>

> Use this project only on systems you own or are explicitly authorized to test. A Turnstile token is short-lived, hostname-sensitive, and does not authenticate a user or create an application session.

## Features

- Multi-layer sitekey detection: URL parameters, static HTML, same-origin scripts, browser DOM, and JavaScript bundles.
- Invisible and visible Turnstile solving through Camoufox.
- HTTP, HTTPS, SOCKS4, SOCKS5, and SOCKS5H proxy support for both detection and browser traffic.
- Bounded retries, exponential backoff with jitter, response-size limits, and per-attempt deadlines.
- Sequential browser reuse with `AlapAlap.solve_many()` and parallel batches with `solve_batch()`.
- Flask REST API with API-key authentication, rate limiting, SSRF protection, browser pooling, and a bounded job queue.
- YAML and environment-variable configuration with validation.
- Atomic, thread-safe sitekey database writes, token redaction, and token-freshness metadata.
- Typer/Rich CLI, structured logging, JSONL result files, and CSV/JSON/Markdown exports.

## Requirements

- Python 3.10 or newer. CI currently tests Python 3.10, 3.11, and 3.12.
- Camoufox browser files (`camoufox fetch`).
- Playwright Chromium for the CLI health check (`python -m playwright install chromium`).

## Installation

### Windows setup script

```powershell
git clone https://github.com/idugeni/alap-alap.git
Set-Location alap-alap
.\setup.bat
.\run.bat --help
.\run.bat solve https://example.com/login
```

`setup.bat` creates `.venv`, installs `requirements.txt`, and attempts to run `camoufox fetch` and `playwright install chromium`. Browser-command output is suppressed and the script does not fail when either command fails, so rerun the commands under Manual installation without suppression if browser setup is in doubt. `run.bat` forwards all remaining arguments to `python main.py`.

### Manual installation

```bash
git clone https://github.com/idugeni/alap-alap.git
cd alap-alap
python -m venv .venv
```

Activate the environment:

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux or macOS
source .venv/bin/activate
```

Install the package and browser files:

```bash
python -m pip install -e .
camoufox fetch
python -m playwright install chromium
```

The editable installation provides both entry points:

```bash
alap-alap --help
python main.py --help
```

The CLI `setup` command is a lightweight package-discovery check, not a complete browser-artifact check. It uses Python module discovery for `requests`, `camoufox`, and `playwright`; it does not import those packages to prove they work. `python main.py setup --check-only` reports a module that cannot be found without installing anything. Without `--check-only`, a missing module causes `requirements.txt` to be installed. The command then attempts `camoufox fetch` only when `camoufox` or `playwright` was initially missing; a failed fetch produces a warning but does not make the command fail. It neither verifies existing Camoufox files nor installs Playwright Chromium. Run the browser commands above explicitly and check their exit status.

## Command-line interface

### Common commands

```bash
# Detect a sitekey and solve it
python main.py solve https://example.com/login

# Skip detection when the sitekey is already known
python main.py solve https://example.com/login --sitekey 0x4AAAAAAAQV1p8gT2jN3m4

# Visible mode, proxy, retries, and a per-attempt deadline
python main.py solve https://example.com/login \
  --visible \
  --proxy socks5://user:pass@proxy.example:1080 \
  --retries 3 \
  --timeout 90

# Detect without solving
python main.py detect https://example.com/login

# Process a URL file in parallel
python main.py batch urls.txt --workers 3
python main.py batch urls.txt --proxy-file proxies.txt

# Inspect runtime state
python main.py health
python main.py info
python main.py config
python main.py config --json --section solver

# Manage the local sitekey database
python main.py sitekeys list
python main.py sitekeys list --status active
python main.py sitekeys search example.com
python main.py sitekeys export --format csv --output sitekeys.csv
python main.py sitekeys stats
python main.py sitekeys prune --days 30 --failed

# Start the REST API
python main.py server
```

On PowerShell, place a multiline command on one line or replace Bash's `\` continuation with PowerShell's backtick.

### Command reference

| Command | Purpose |
|---|---|
| `solve <url>` | Detect a sitekey if needed and produce a token. |
| `batch <file>` | Solve one URL per line with parallel browser workers; `-` reads stdin. |
| `detect <url>` | Detect a sitekey and report the layer that found it. |
| `sitekeys <action> [query]` | Run `list`, `search`, `export`, `stats`, or `prune`. |
| `health` | Check discovery of selected Python modules, Playwright Chromium, logs, database, and config. |
| `info` | Show package, Python, logging, and database information. |
| `config` | Show effective settings and corresponding environment variables. |
| `setup` | Check or install three discoverable browser-stack Python modules and conditionally attempt a Camoufox fetch. |
| `server` | Start the Flask development server. |

### Solve options

| Option | Meaning |
|---|---|
| `--sitekey`, `-s` | Use a known sitekey instead of running detection. |
| `--proxy`, `-p` | Proxy URL or `user:pass@host:port`. |
| `--visible`, `-v` | Show the browser and use the visible-widget flow. |
| `--retries`, `-r` | Total attempts; values below one are normalized to one and config caps the maximum. Default: `1`. |
| `--timeout`, `-t` | Per-attempt wall-clock budget in seconds; the solver config is used when omitted. |
| `--output`, `-o` | JSONL destination. Default: `results.txt`. |
| `--json` | Also print the raw result object, including `url`, as JSON. |
| `--no-install` | Fail when a checked Python module cannot be discovered instead of installing dependencies. |

### Batch input and options

The URL file contains one URL per line. Empty lines and lines beginning with `#` are ignored. A proxy file follows the same format and is assigned to workers round-robin.

| Option | Meaning |
|---|---|
| `--workers`, `-w` | Browser workers; defaults to `batch.MAX_WORKERS` and is capped by `batch.WORKER_LIMIT` and the URL count. |
| `--proxy`, `-p` | One proxy for every worker. |
| `--proxy-file` | Proxy pool assigned to workers round-robin; overrides `--proxy`. |
| `--visible`, `-v` | Use visible browsers. |
| `--retries`, `-r` | Attempts per URL; values below one are normalized to one and `retry.MAX_RETRIES` caps the maximum. Default: `1`. |
| `--timeout`, `-t` | Per-attempt deadline; the solver config is used when omitted. |
| `--output`, `-o` | JSONL destination. Default: `results.txt`. |
| `--no-install` | Fail when a checked Python module cannot be discovered instead of installing dependencies. |

### Detect options

`detect` writes a `sitekey_only` or `no_sitekey` record to the result file. A found sitekey is also added to the local database with `unknown` status.

| Option | Meaning |
|---|---|
| `--proxy`, `-p` | Proxy used by HTTP and browser detection. |
| `--output`, `-o` | JSONL destination. Default: `results.txt`. |
| `--no-install` | Fail when a checked Python module cannot be discovered instead of installing dependencies. |

### Sitekey database options

| Argument or option | Meaning |
|---|---|
| `list` | List every entry; `--status active|inactive|unknown` filters the table. |
| `search <query>` | Search sitekey, URL, domain, platform, and tags. `--query`, `-q` is also accepted. |
| `export` | Export with `--format`, `-f` set to `markdown`/`md`, `csv`, or `json`; optional `--output`, `-o` overrides the generated filename. |
| `stats` | Show database totals, solve counts/rate, average solve time, and fresh-token count. |
| `prune` | Remove entries selected by `--days <n>`, `--failed`, or both. At least one selector is required. |

Default export names are `SITEKEYS.md`, `sitekeys.csv`, and `sitekeys.json`.

### Inspection, setup, and server options

| Command | Options and behavior |
|---|---|
| `health` | Has no command-specific options. Uses module discovery for eight dependency rows, then separately imports Playwright and starts `sync_playwright()` to inspect the Chromium executable path. It also reports log statistics, database entry count, and config discovery, but does not verify Camoufox browser files. |
| `info` | Has no command-specific options. Shows version, Python, license, log statistics, and database solve statistics. |
| `config` | `--json` emits JSON; `--section`, `-s` selects one config section and rejects unknown names. |
| `setup` | `--check-only` prevents installation. The package/browser limitations described under Installation still apply. |
| `server` | `--host`, `-h`; `--port`, `-p`; and `--debug`, `-d`. Host and port fall back to `api.HOST` and `api.PORT`. |

### Result output path

`solve`, `batch`, and `detect` always pass their `--output` value to the writer, and each command currently defaults that option to `results.txt`. Changing `storage.RESULTS_FILE` does not change those CLI defaults; pass `--output <path>` explicitly. `storage.RESULTS_FILE` remains the fallback used by the internal result writer when no path is supplied.

## Python API

### Detect and solve

```python
from src.core import AlapAlap

with AlapAlap(timeout=90) as alap:
    result = alap.solve(
        "https://example.com/login",
        invisible=True,
        retries=2,
    )

if result["success"]:
    print(result["token"])
else:
    print(result["error"])
```

Use `solve_with_sitekey()` to skip detection:

```python
with AlapAlap(proxy="user:pass@proxy.example:8080") as alap:
    result = alap.solve_with_sitekey(
        "https://example.com/login",
        "0x4AAAAAAAQV1p8gT2jN3m4",
        retries=2,
        timeout=90,
    )
```

`AlapAlap` starts its browser lazily when it is not used as a context manager. Call `close()` explicitly in that form. Direct library use allows private targets by default; pass `allow_private_hosts=False` when URLs are not fully trusted.

### Multiple URLs

```python
from src.core import AlapAlap, solve_batch

# Sequential: one browser is reused.
with AlapAlap() as alap:
    sequential = alap.solve_many(
        ["https://a.example/login", "https://b.example/login"],
        retries=2,
    )

# Parallel: one AlapAlap/browser per worker; input order is preserved.
parallel = solve_batch(
    ["https://a.example/login", "https://b.example/login"],
    proxies=["proxy-a.example:8080", "proxy-b.example:8080"],
    workers=2,
    retries=2,
    allow_private_hosts=False,
)
```

### Detection only

```python
from src.detector import SitekeyDetector

with SitekeyDetector(allow_private_hosts=False) as detector:
    sitekey, method = detector.detect_with_method("https://example.com/login")

print(sitekey, method)  # method: url, html, dom, or js_bundle
```

### Result contracts

`solve()` and `solve_with_sitekey()` return the standard solve fields:

```json
{
  "success": true,
  "token": "0.example-token",
  "sitekey": "0x4AAAAAAA...",
  "error": null,
  "time": 2.5,
  "attempts": 1
}
```

Each `solve_many()` and `solve_batch()` item is the same shape plus the input `url`:

```json
{
  "url": "https://example.com/login",
  "success": true,
  "token": "0.example-token",
  "sitekey": "0x4AAAAAAA...",
  "error": null,
  "time": 2.5,
  "attempts": 1
}
```

## REST API

Start the local development server:

```bash
python main.py server --host 127.0.0.1 --port 5000
```

The server binds to loopback by default. If `ALAP_API_KEY` is set, every endpoint except `/` and `/health` accepts either `X-API-Key: <key>` or `Authorization: Bearer <key>`.

### Endpoints

| Method | Path | Access | Description |
|---|---|---|---|
| `GET` | `/` | Public | Service version, auth state, and endpoint index. |
| `GET` | `/health` | Public | Dependency and pool health. |
| `POST` | `/solve` | Protected when configured | Queue a solve and wait within the request budget. |
| `POST` | `/jobs` | Protected when configured | Queue a solve and immediately return `202`. |
| `GET` | `/jobs/<id>` | Protected when configured | Poll one retained job. |
| `GET` | `/jobs?limit=50` | Protected when configured | List recent jobs, newest first. |
| `POST` | `/detect` | Protected when configured | Detect a sitekey without solving. |
| `GET` | `/sitekeys` | Protected when configured | Filter stored keys by `status`, `domain`, `q`, and `limit`. |
| `GET` | `/stats` | Protected when configured | Database and browser-pool statistics. |

Authentication is disabled when `api.KEY` is empty, which is convenient for loopback development. Do not expose an unauthenticated server to a network. Protected endpoints are also subject to a sliding-window limit keyed by the direct socket peer. The limiter is in-process, ignores forwarding headers such as `X-Forwarded-For`, and is not shared across WSGI workers; account for those properties when placing the app behind a proxy or running multiple workers. Every response receives an `X-Request-ID` header.

### Solve request

`POST /solve` and `POST /jobs` accept the same schema-validated JSON object:

```json
{
  "url": "https://example.com/login",
  "sitekey": "0x4AAAAAAA...",
  "proxy": "socks5://user:pass@proxy.example:1080",
  "invisible": true,
  "retries": 2,
  "timeout": 90
}
```

| Field | Required | Default and validation |
|---|---:|---|
| `url` | Yes | Must be a nonblank string and pass the HTTP(S)/SSRF guard. |
| `sitekey` | No | `null`; a nonempty value skips detection, while `null` or an empty string runs detection. |
| `proxy` | No | `null`; accepts the proxy forms supported by the library. |
| `invisible` | No | `true`; compatible boolean representations are coerced by Pydantic. |
| `retries` | No | `1`; coerced to an integer when compatible, then constrained from `1` through `10`. |
| `timeout` | No | `null`, which uses `api.SOLVE_TIMEOUT_S`; otherwise coerced to a number when compatible and constrained to greater than `0` through `600` seconds. |

Unknown fields are forbidden and the body must be a JSON object, but scalar validation is not globally strict: compatible values such as `"2"` for `retries` or `"false"` for `invisible` can be coerced.

```bash
curl -X POST http://127.0.0.1:5000/solve \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_KEY>" \
  -d '{"url":"https://example.com/login","retries":2}'
```

A completed successful request returns the standard solve result with HTTP `200`. A completed result with `success=false` returns `502`. If the request wait budget expires while work continues, `/solve` returns `202`, the serialized job, a `message`, a `poll` URL, and a `Location` header. Queue saturation returns `503` with `retry_after: 5` in the JSON body. A worker-level job error returns `500`.

When `api.RETURN_TOKENS=false`, result-bearing completed solve and `done` job responses set `token` to `null` and add `token_withheld: true`. Queued/running snapshots and worker-error responses have no result token to withhold, so they do not add that marker.

### Asynchronous jobs

```bash
curl -X POST http://127.0.0.1:5000/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_KEY>" \
  -d '{"url":"https://example.com/login"}'
```

Accepted-job snapshot example (`202` with `Location: /jobs/<id>`):

```json
{
  "job_id": "ab12cd34",
  "status": "queued",
  "url": "https://example.com/login",
  "success": null,
  "queued_for": 0.001,
  "solve_time": 0.0,
  "poll": "/jobs/ab12cd34"
}
```

A worker can pick up or even finish the job before this response is serialized, so the snapshot may already report `running`, `done`, or `error` instead of `queued`.

Poll with:

```bash
curl http://127.0.0.1:5000/jobs/ab12cd34 -H "X-API-Key: <API_KEY>"
```

All serialized jobs contain `job_id`, `status`, `url`, `queued_for`, and `solve_time`. `success` is `null` while queued or running. A `done` job adds the standard solve fields; an `error` job adds `success=false` and `error`.

Jobs can be `queued`, `running`, `done`, or `error`. Finished jobs older than `api.JOB_TTL_S` become eligible for removal, and `api.JOB_MAX_RETAINED` is the target maximum used when trimming finished jobs. Cleanup is not continuous or background-driven: TTL eviction and cap enforcement run only when a later job is submitted. Therefore an expired job can remain retrievable through `GET /jobs/<id>` or `GET /jobs` and continue contributing to the `retained_jobs` aggregate shown by `/health` and `/stats` until another submission triggers a sweep. The retained count can also remain above the configured target when multiple in-flight jobs finish after the last sweep. In-flight jobs themselves are never removed by the cap.

`GET /jobs` defaults `limit` to `50`. Any parseable integer is accepted and clamped to `1` through `500`; a non-integer returns `400`. The response is:

```json
{
  "count": 1,
  "jobs": [
    {
      "job_id": "ab12cd34",
      "status": "running",
      "url": "https://example.com/login",
      "queued_for": 0.012,
      "solve_time": 1.5,
      "success": null
    }
  ],
  "pool": {
    "workers": 2,
    "started": true,
    "pool_enabled": true,
    "browser_launches": 2,
    "queued": 0,
    "running": 1,
    "completed": 0,
    "failed": 0,
    "retained_jobs": 1,
    "queue_capacity": 32
  }
}
```

### Detection endpoint

`POST /detect` accepts only `url` and optional `proxy`:

```json
{
  "url": "https://example.com/login",
  "proxy": "socks5://user:pass@proxy.example:1080"
}
```

A match returns `200`:

```json
{
  "success": true,
  "sitekey": "0x4AAAAAAA...",
  "method": "html"
}
```

No match returns `404` with `{"success": false, "error": "Sitekey not found"}`. An invalid body or blocked URL returns `400`; an internal detection error returns `500`.

### Sitekeys and statistics

`GET /sitekeys` supports:

| Query | Behavior |
|---|---|
| `status` | Exact status-string filter; normal stored values are `active`, `inactive`, and `unknown`. Other strings are not rejected and normally produce an empty result. |
| `domain` | Exact domain lookup. Ignored when `q` is also supplied. |
| `q` | Free-text database search. |
| `limit` | Defaults to `100`; any parseable integer is clamped to `1` through `1000`, while a non-integer returns `400`. |

The response contains `count`, `total`, and a `sitekeys` array. Each item contains `sitekey`, `platform`, `domain`, `status`, `solve_count`, `success_count`, `success_rate`, `last_seen`, `token_fresh`, `token_expires_in`, and `tags`. Tokens themselves are not returned by this endpoint.

`GET /stats` returns `success=true`; database fields `total_sitekeys`, `active_sitekeys`, `inactive_sitekeys`, `unknown_sitekeys`, `total_domains`, `total_solve_attempts`, `successful_solves`, `success_rate`, `avg_solve_time`, and `fresh_tokens`; plus the `pool` object shown above.

### Service and health payloads

`GET /` returns `name`, package `version`, `auth_required`, and an endpoint index. `GET /health` returns `status`, `service`, package `version`, a dependency-status map, and current `pool` statistics. These two endpoints are public and bypass API-key and rate-limit checks.

### Errors and status codes

The common error envelope is:

```json
{
  "success": false,
  "error": "Error message"
}
```

Some errors add context such as `retry_after` or `job_id`. Unhandled application errors are logged with details but return a generic message.

| Status | Meaning in this API |
|---:|---|
| `200` | Successful read/detection/solve, or a queued/running job poll. |
| `202` | Job accepted, or `/solve` is still working and must be polled. |
| `400` | Missing/malformed/schema-invalid JSON, unsafe URL, or non-integer `limit`. |
| `401` | Missing or invalid API key when authentication is enabled. |
| `404` | Endpoint/job not found, or `/detect` found no sitekey. |
| `405` | Method not allowed. |
| `429` | Rate limit exceeded; includes JSON `retry_after` and a `Retry-After` header. |
| `500` | Worker, detection, or internal server error. |
| `502` | Solving completed but returned `success=false`. |
| `503` | The bounded job queue is full. |

### Browser pool

Each worker owns one `AlapAlap` instance on its own thread because Playwright's synchronous API is thread-bound. Browsers stay warm when `api.POOL_ENABLED=true`, relaunch when the requested proxy changes, and recycle after `api.POOL_MAX_SOLVES_PER_BROWSER` solves when that value is nonzero.

`/health`, `/stats`, and `GET /jobs` expose pool state including workers, launches, queued/running/completed/failed counts, retained jobs, and queue capacity.

### Security defaults

| Setting | Default | Purpose |
|---|---:|---|
| `api.HOST` | `127.0.0.1` | Keep the development server off the network. |
| `api.KEY` | empty | Optional auth; a warning is logged if an open server binds off-loopback. |
| `api.ALLOW_PRIVATE_HOSTS` | `false` | Block loopback, private, link-local, metadata, and non-HTTP(S) targets. |
| `api.RATE_LIMIT_REQUESTS` | `60` | Per-peer requests per 60-second default window. |
| `api.MAX_CONCURRENT_SOLVES` | `2` | Browser workers and concurrent solves. |
| `api.QUEUE_MAX_SIZE` | `32` | Accepted jobs waiting for workers. |
| `api.RETURN_TOKENS` | `true` | Include tokens in REST responses; set false for shared deployments. |

The bundled server is Flask's development server. Put a production WSGI server and TLS in front of it before any authorized network deployment. Never enable debug mode in production.

## Configuration

Settings resolve in this order, with later sources winning:

1. Frozen dataclass defaults in `src/config.py`.
2. `alap-alap.yml`, `alap-alap.yaml`, `.alap-alap.yml`, or the file named by `ALAP_CONFIG_FILE`.
3. Environment variables named `ALAP_<SECTION>_<FIELD>`.

Example YAML:

```yaml
browser:
  HTTP_TIMEOUT: 20
solver:
  SOLVE_TIMEOUT_S: 90
api:
  KEY: replace-with-a-long-random-value
  RATE_LIMIT_REQUESTS: 120
  RETURN_TOKENS: false
batch:
  MAX_WORKERS: 4
```

PowerShell overrides:

```powershell
$env:ALAP_SOLVER_SOLVE_TIMEOUT_S = "90"
$env:ALAP_API_KEY = "replace-with-a-long-random-value"
$env:ALAP_API_RETURN_TOKENS = "false"
```

POSIX shell overrides:

```bash
export ALAP_SOLVER_SOLVE_TIMEOUT_S=90
export ALAP_API_KEY='replace-with-a-long-random-value'
export ALAP_API_RETURN_TOKENS=false
```

Useful settings include:

| Section | Settings |
|---|---|
| `browser` | HTTP retries/backoff/size limit, page timeouts, DOM attempts, bundle scan limit, user agent. |
| `mouse` | Movement speeds, delays, and `PATH_MAX_STEPS`. |
| `solver` | Widget polling, click offsets, `SOLVE_TIMEOUT_S`, and `PAGE_LOAD_TIMEOUT_MS`. |
| `retry` | `MAX_RETRIES`, exponential delay bounds, rate-limit delay, and jitter. |
| `logging` | Console/file levels, rotation, retention, compression, and JSON file output. |
| `storage` | Database path, result-writer fallback path, token redaction, preview length, and token TTL. See the CLI output-path caveat above. |
| `api` | Bind/auth/rate limits, SSRF policy, request budgets, token responses, pool, queue, and submit-triggered job retention cleanup. |
| `batch` | Worker defaults/limit, dispatch stagger, and continue-on-error behavior. |

Run `python main.py config` for every current setting, its effective value, and its environment-variable name. Invalid files, unknown fields, and out-of-range values are reported; startup falls back to defaults with a warning if global config loading fails.

## Local data and generated files

- `results.txt` is newline-delimited JSON written by CLI `solve`, `batch`, and `detect` unless `--output` is supplied. Records contain `url`, `sitekey`, `token`, `status`, `error`, and `timestamp`.
- Result files can contain complete solved tokens. `storage.REDACT_STORED_TOKENS` protects database storage, not JSONL result output; protect and delete result files accordingly.
- `captcha_database.json` stores discovered sitekeys and solve metadata using atomic replacement under a lock.
- Database tokens are truncated by default (`storage.REDACT_STORED_TOKENS=true`).
- `token_obtained_at` and `storage.TOKEN_TTL_S` drive freshness reporting; a stored token is not a reusable login session.
- `sitekeys export` creates `SITEKEYS.md`, `sitekeys.csv`, or `sitekeys.json` unless another output path is supplied.
- Logs are written below `logs/` with configurable rotation and retention.

These runtime files, local YAML overrides, virtual environments, caches, coverage output, egg-info, and local tool state are excluded by `.gitignore`. Do not force-add tokens, credentials, logs, databases, or generated exports.

## Project structure

```text
alap-alap/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE/
│   └── workflows/
├── src/
│   ├── api/
│   │   ├── pool.py             # Browser workers and queued jobs
│   │   └── server.py           # Flask application factory and routes
│   ├── core/main.py            # AlapAlap facade and batch helpers
│   ├── detector/sitekey_detector.py
│   ├── solver/captcha_solver.py
│   ├── cli.py                  # Typer application
│   ├── config.py               # Defaults, YAML/env overrides, validation
│   ├── errors.py               # Public exception hierarchy
│   ├── logger.py               # Loguru setup and retention
│   ├── models.py               # Shared Pydantic/request/result models
│   ├── proxy.py                # Proxy parsing and adapters
│   ├── security.py             # SSRF, API-key, and rate-limit helpers
│   └── sitekeys_db.py          # Atomic sitekey persistence and exports
├── tests/
│   ├── unit/                   # Browser-free unit tests
│   └── integration/            # Opt-in real-browser tests
├── main.py                     # Thin shim to src.cli:app
├── pyproject.toml              # Package metadata and tool configuration
├── requirements.txt            # Runtime dependencies for setup.bat
├── setup.bat
└── run.bat
```

## Testing

The default Pytest configuration excludes integration tests because they launch a real browser.

```bash
# Default non-integration suite
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/unit/ -v

# Opt-in real-browser tests
python -m pytest -m integration tests/ -v

# Coverage
python -m pytest tests/ --cov=src --cov-report=term-missing --cov-report=xml
```

## Development

Install development tools:

```bash
python -m pip install -e ".[dev]"
python -m pip install pre-commit
pre-commit install
```

Run the same quality gates as CI:

```bash
ruff check src/ tests/ main.py
black --check src/ tests/ main.py
pyright src/
python -m pytest tests/
```

CI runs those checks on Python 3.10, 3.11, and 3.12, verifies installed entry points, builds the distribution, and checks it with Twine. Real-browser integration tests run only when the CI workflow is manually dispatched.

Before opening a pull request:

```bash
pre-commit run --all-files
python -m pytest tests/
git diff --check
git status --short
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for repository conventions and the generated-file policy.

## Error behavior

Intentional library exceptions derive from `AlapAlapError`. Configuration, proxy parsing, browser lifecycle, dependencies, solving, and unsafe URLs have dedicated exception classes in `src/errors.py`.

The high-level `AlapAlap.solve*()` methods normally return `success=false` with an error string instead of propagating solve failures. Low-level classes may raise typed exceptions—for example, `CaptchaSolver.solve()` raises `BrowserNotStartedError` if `start()` was not called.

## License

Alap-Alap is available under the [MIT License](LICENSE).
