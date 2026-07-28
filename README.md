<div align="center">

# 🦅 Alap-Alap

### Cloudflare Turnstile Captcha Solver

*Like a falcon — fast, precise, and unstoppable*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-00FF00?style=for-the-badge)](LICENSE)
[![Camoufox](https://img.shields.io/badge/Browser-Camoufox-FF6B00?style=for-the-badge&logo=firefox&logoColor=white)](https://camoufox.com)
[![Tests](https://img.shields.io/badge/Tests-31%20Passed-brightgreen?style=for-the-badge)](#testing)
[![CI](https://img.shields.io/badge/CI-Passing-brightgreen?style=for-the-badge)](https://github.com/idugeni/alap-alap/actions)
[![Status](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)]()

<br>

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [API](#api-reference) • [Testing](#testing)

</div>

---

## ✨ Features

<table>
<tr>
<td>

🔍 **Auto Detection** — Automatic sitekey extraction from URLs

</td>
<td>

🛡️ **Anti-Fingerprint** — Camoufox browser protection

</td>
</tr>
<tr>
<td>

🎯 **High Accuracy** — Smart mouse movement simulation

</td>
<td>

⚡ **Fast** — Optimized solving pipeline

</td>
</tr>
<tr>
<td>

🧩 **Modular** — Clean, separated components

</td>
<td>

📝 **Smart Logging** — Loguru with auto-cleanup

</td>
</tr>
<tr>
<td>

⚙️ **Configurable** — All settings in one place

</td>
<td>

🎨 **Rich CLI** — Beautiful terminal output

</td>
</tr>
<tr>
<td>

💾 **Database** — Store solved captchas for sharing

</td>
<td>

🔄 **Auto Retry** — Exponential backoff

</td>
</tr>
</table>

---

## 📦 Installation

### Option 1: Auto Setup (Recommended)

```bash
# Clone
git clone https://github.com/idugeni/alap-alap.git
cd alap-alap

# Run setup (creates .venv + installs everything)
setup.bat

# Or just run - auto-installs if missing
run.bat https://example.com/login
```

### Option 2: Manual Setup

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install browsers
camoufox fetch
playwright install chromium
```

---

## 🚀 Usage

### CLI Commands

```bash
# Show help
python main.py --help

# Solve captcha (auto-detect sitekey)
python main.py solve https://example.com/login

# Detect sitekey only
python main.py detect https://example.com/login

# Solve with known sitekey
python main.py solve https://example.com/login --sitekey 0x4AAAAAAAQV1p8gT2jN3m4

# Solve with proxy
python main.py solve https://example.com/login --proxy user:pass@host:port

# Solve with retry
python main.py solve https://example.com/login --retries 3

# Check dependencies
python main.py health

# Show project info
python main.py info

# Manage sitekeys database
python main.py sitekeys list
python main.py sitekeys search etherscan
python main.py sitekeys export
python main.py sitekeys stats
```

### Python API

```python
from src.core import AlapAlap

# Auto-detect sitekey and solve
with AlapAlap() as alap:
    result = alap.solve("https://example.com/login")
    
    if result["success"]:
        print(f"Token: {result['token']}")
        print(f"Sitekey: {result['sitekey']}")
        print(f"Time: {result['time']:.1f}s")
```

### Detect Sitekey Only

```python
from src.detector import SitekeyDetector

detector = SitekeyDetector()
sitekey = detector.detect("https://example.com/login")

if sitekey:
    print(f"Found: {sitekey}")
```

---

## 📋 CLI Reference

| Command | Description |
|---------|-------------|
| `python main.py solve <url>` | Solve captcha (auto-detect sitekey) |
| `python main.py detect <url>` | Detect sitekey only |
| `python main.py health` | Check dependencies status |
| `python main.py info` | Show project information |
| `python main.py sitekeys list` | List all sitekeys |
| `python main.py sitekeys search <query>` | Search sitekeys |
| `python main.py sitekeys export` | Export to SITEKEYS.md |
| `python main.py sitekeys stats` | Show statistics |

### Solve Options

| Option | Description |
|--------|-------------|
| `--sitekey, -s` | Use known sitekey |
| `--proxy, -p` | Use proxy (`user:pass@host:port`) |
| `--visible, -v` | Use visible browser mode |
| `--retries, -r` | Number of retry attempts |
| `--output, -o` | Output file (default: `results.txt`) |

---

## 🔌 API Reference

### `AlapAlap`

Main solver class.

```python
AlapAlap(proxy=None, headless=True)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `proxy` | `str` | `None` | Proxy string (`user:pass@host:port`) |
| `headless` | `bool` | `True` | Run browser headless |

**Methods:**

```python
# Auto-detect sitekey and solve
result = alap.solve(url, invisible=True)

# Solve with known sitekey
result = alap.solve_with_sitekey(url, sitekey, invisible=True)
```

### `SitekeyDetector`

Sitekey detection class.

```python
from src.detector import SitekeyDetector

detector = SitekeyDetector(proxy=None)
sitekey = detector.detect(url)
```

### `CaptchaSolver`

Low-level solver class.

```python
from src.solver import CaptchaSolver

solver = CaptchaSolver(proxy=None, headless=True)
solver.start()
token = solver.solve(url, sitekey, invisible=True)
solver.stop()
```

### `config`

Centralized configuration.

```python
from src.config import config

# Browser settings
print(config.browser.USER_AGENT)
print(config.browser.HTTP_TIMEOUT)

# Mouse movement settings
print(config.mouse.MOVE_THRESHOLD_PX)

# Solver settings
print(config.solver.INVISIBLE_SOLVE_MAX_ATTEMPTS)
```

---

## 📄 Response Format

### CLI Output (`results.txt`)

```json
{
  "url": "https://example.com/login",
  "sitekey": "0x4AAAAAAA...",
  "token": "0.your-captcha-token...",
  "status": "success",
  "error": null,
  "timestamp": "2026-07-28T15:00:00+00:00"
}
```

### Status Values

| Status | Description |
|--------|-------------|
| `success` | Sitekey + token retrieved |
| `sitekey_only` | Only sitekey detected |
| `failed` | Solve failed (check `error`) |
| `no_sitekey` | Sitekey not found |

### Python Response

```python
{
    "success": True,
    "token": "0.your-captcha-token...",
    "sitekey": "0x4AAAAAAA...",
    "error": None,
    "time": 2.5
}
```

---

## 📁 Project Structure

```
alap-alap/
├── main.py                 # CLI entry point
├── setup.bat               # Auto setup script
├── run.bat                 # Auto run script
├── src/
│   ├── __init__.py
│   ├── config.py           # Centralized configuration
│   ├── logger.py           # Logging with auto-cleanup
│   ├── sitekeys_db.py      # Captcha database
│   ├── core/
│   │   └── main.py         # AlapAlap main class
│   ├── detector/
│   │   └── sitekey_detector.py
│   └── solver/
│       └── captcha_solver.py
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_detector.py
│   │   ├── test_logger.py
│   │   ├── test_sitekeys_db.py
│   │   └── test_solver.py
│   └── integration/
│       └── test_full_flow.py
├── requirements.txt
├── pyproject.toml
└── .github/workflows/ci.yml
```

---

## ⚙️ Configuration

All settings are centralized in `src/config.py`:

```python
from src.config import config

# Browser settings
config.browser.USER_AGENT        # Chrome user agent
config.browser.HTTP_TIMEOUT      # HTTP request timeout
config.browser.PAGE_GOTO_TIMEOUT_MS  # Page load timeout

# Mouse movement settings
config.mouse.MOVE_THRESHOLD_PX   # Movement threshold
config.mouse.SPEED_FACTOR        # Speed calculation factor

# Solver settings
config.solver.INVISIBLE_SOLVE_MAX_ATTEMPTS  # Max attempts
config.solver.IFRAME_WAIT_MAX_ATTEMPTS      # Iframe wait

# Sitekey validation
config.sitekey.MIN_LENGTH        # Minimum sitekey length
config.sitekey.FALSE_POSITIVES   # Invalid sitekey list
```

---

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run unit tests only
python -m pytest tests/unit/ -v

# Run integration tests
python -m pytest tests/integration/ -v

# Run with coverage
python -m pytest tests/ --cov=src
```

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Type check
pyright src/
```

---

## 📋 Requirements

- Python 3.10+
- Camoufox
- Playwright
- Requests
- Rich
- Typer
- Loguru
- Pydantic

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with 🦅 by [idugeni](https://github.com/idugeni)**

*Fast as a falcon, smart as a hunter*

[![GitHub](https://img.shields.io/badge/GitHub-idugeni-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/idugeni/alap-alap)

</div>
