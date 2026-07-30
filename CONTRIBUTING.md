# Contributing to Alap-Alap

Thank you for improving Alap-Alap. This guide reflects the current `src` package layout, Python support, CI gates, browser-backed integration tests, and generated-file policy.

## Before you start

- Use Python 3.10 or newer. CI tests Python 3.10, 3.11, and 3.12.
- Use the project only against systems you own or are explicitly authorized to test.
- Search existing issues and pull requests before starting overlapping work.
- Never include credentials, proxy passwords, API keys, CAPTCHA tokens, local databases, or private target details in an issue or commit.

## Development setup

Clone and create a virtual environment:

```bash
git clone https://github.com/idugeni/alap-alap.git
cd alap-alap
python -m venv .venv
```

Activate it:

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux or macOS
source .venv/bin/activate
```

Install the package, development tools, and browser files:

```bash
python -m pip install -e ".[dev]"
camoufox fetch
python -m playwright install chromium
```

Windows users can run `setup.bat` for runtime setup, but contributors still need `python -m pip install -e ".[dev]"` for test and quality tools.

Optional pre-commit setup:

```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

The configured hooks run Ruff, Black, repository hygiene checks, secret detection, and the unit suite. Integration tests remain opt-in because they start a real browser.

## Repository layout

```text
alap-alap/
├── src/
│   ├── api/
│   │   ├── pool.py             # Browser pool, queue, and job lifecycle
│   │   └── server.py           # Flask app factory and REST routes
│   ├── core/main.py            # AlapAlap facade and batch orchestration
│   ├── detector/               # Sitekey detection layers
│   ├── solver/                 # Camoufox Turnstile solver
│   ├── cli.py                  # Typer command-line interface
│   ├── config.py               # Defaults, overrides, and validation
│   ├── errors.py               # Exception hierarchy
│   ├── logger.py               # Logging setup and retention
│   ├── models.py               # Shared Pydantic models
│   ├── proxy.py                # Proxy parsing/adapters
│   ├── security.py             # SSRF, authentication, rate limiting
│   └── sitekeys_db.py          # Atomic persistence and exports
├── tests/
│   ├── unit/                   # Browser-free unit tests
│   └── integration/            # Opt-in Camoufox tests
├── main.py                     # Entry-point shim
├── pyproject.toml              # Package and tool configuration
├── requirements.txt            # Runtime dependencies for setup.bat
└── .github/workflows/          # CI and release publishing
```

Imports use the package paths visible in the repository, for example:

```python
from src.core import AlapAlap
from src.detector import SitekeyDetector
```

## Making a change

1. Create a focused branch, such as `fix/url-normalization` or `feat/job-cancellation`.
2. Keep the change limited to one concern.
3. Follow existing public result and request contracts unless the change intentionally documents a breaking change.
4. Add or update tests for behavior changes. Do not make unit tests depend on a real browser or third-party site.
5. Update README/API/config documentation when a command, option, setting, endpoint, response, or default changes.
6. Add a concise entry under `Unreleased` in `CHANGELOG.md` for user-visible changes.
7. Run the checks below before opening a pull request.

## Coding standards

- Target Python 3.10 syntax and behavior.
- Maximum line length is 100 characters.
- Format with Black.
- Lint with Ruff using the rules in `pyproject.toml`.
- Add type hints to public interfaces and keep Pyright in basic mode clean.
- Add docstrings to public classes, functions, and methods.
- Prefer typed project exceptions from `src/errors.py` for deliberate failure modes.
- Preserve browser and HTTP cleanup with context managers or `finally` blocks.
- Keep network-facing input behind the URL validation and API security boundaries.
- Avoid logging secrets; use masked proxy values and redacted tokens.

Format and lint:

```bash
black src/ tests/ main.py
ruff check src/ tests/ main.py
pyright src/
```

## Testing

The default marker expression in `pyproject.toml` excludes integration tests.

```bash
# Same non-integration suite used by normal CI
python -m pytest tests/ -v

# Fast browser-free suite used by pre-commit
python -m pytest tests/unit/ -q

# One module
python -m pytest tests/unit/test_detector.py -v

# Coverage output used by CI
python -m pytest tests/ --cov=src --cov-report=term-missing --cov-report=xml
```

Integration tests launch Camoufox and must be requested explicitly:

```bash
python -m pytest -m integration tests/ -v
```

Use Cloudflare's documented testing sitekeys and controlled test pages for integration coverage. Do not make CI depend on unrelated third-party websites, personal accounts, or stored tokens.

### Test conventions

- Place deterministic, browser-free tests in `tests/unit/`.
- Place true browser/network flows in `tests/integration/` and mark them `@pytest.mark.integration`.
- Name modules `test_*.py`, classes `Test*`, and functions `test_*`.
- Use `tests/conftest.py` fixtures so storage writes go to temporary directories.
- Mock process, network, browser, and timing boundaries in unit tests.
- Test success, validation failures, cleanup, retries/timeouts, and security boundaries where relevant.

## CI and build checks

Normal pushes and pull requests run:

```bash
ruff check src/ tests/ main.py
black --check src/ tests/ main.py
pyright src/
python -m pytest tests/ --cov=src --cov-report=xml --cov-report=term-missing
```

CI also verifies:

- `alap-alap --help`, config output, and `python main.py info`.
- Wheel and source-distribution builds.
- `twine check` on distribution artifacts.
- Python 3.10, 3.11, and 3.12 for the primary test job.

The real-browser integration job runs only through manual workflow dispatch.

## Configuration and security changes

When adding a setting:

1. Add it to the appropriate frozen dataclass in `src/config.py`.
2. Add validation in `_validate()` if invalid values can break behavior.
3. Use the setting in implementation code; the suite checks for dangling options.
4. Add tests for default, YAML, and environment behavior as appropriate.
5. Document the corresponding `ALAP_<SECTION>_<FIELD>` variable.

When changing the REST API, preserve or intentionally update:

- Pydantic request validation.
- API-key handling and public endpoint exemptions.
- Per-peer rate limiting.
- SSRF protection for every caller-controlled URL.
- Queue/concurrency bounds and generic JSON errors.
- Token withholding via `api.RETURN_TOKENS`.

Security-sensitive changes should explain the threat model and safe default in the pull request.

## Documentation conventions

- Keep examples runnable from the repository root.
- Show both `python main.py` and installed-package behavior only where they differ.
- Do not publish hardcoded pass counts, coverage percentages, or benchmark numbers unless a reproducible command and environment are included.
- Keep endpoint, option, config, response, and project-tree examples synchronized with code.
- Prefer placeholders such as `<API_KEY>` and `proxy.example`; never paste real secrets or tokens.

## Generated and local files

The following are local state and must not be committed or force-added:

- `.venv/`, `venv/`, Python bytecode, `*.egg-info/`, `build/`, and `dist/`.
- `.pytest_cache/`, `.ruff_cache/`, coverage files, and HTML coverage.
- `logs/`, `captcha_database.json`, `results.txt`, and corrupt/temporary database output.
- `SITEKEYS.md`, `sitekeys.csv`, and `sitekeys.json` generated by export commands.
- Local `alap-alap.yml` variants, which can contain API keys or environment-specific settings.
- `.mimocode/`, `.serena/`, IDE settings, and OS metadata.

Before committing, inspect exactly what Git sees:

```bash
git status --short
git diff --check
git diff --stat
```

Do not use `git add -f` to bypass these exclusions. If a fixture resembles generated data but belongs in tests, keep it minimal, synthetic, and under `tests/`.

## Pull requests

A good pull request:

- Has a focused title under 70 characters.
- Explains the problem, behavior change, and compatibility/security impact.
- Lists the exact validation commands run.
- Includes tests for changed behavior or explains why tests are not applicable.
- Updates README and CHANGELOG for user-visible changes.
- Contains no unrelated formatting, generated artifacts, local state, or secrets.

Run this final checklist:

```bash
pre-commit run --all-files
python -m pytest tests/
git diff --check
git status --short
```

Do not skip hooks to make a failing change pass. Fix the underlying issue instead.

## Reporting bugs

Use the bug-report template and include:

- A minimal reproduction command or code sample.
- Expected and actual behavior.
- OS, Python version, Alap-Alap version, and entry point.
- Whether a proxy, YAML override, environment override, API server, or pool is involved.
- Redacted logs and tracebacks where useful.

Remove tokens, passwords, API keys, private URLs, and account information before submitting.
