# Alap-Alap

<div align="center">

🦅 **Cloudflare Turnstile Captcha Solver**

*Like a falcon - fast, precise, and unstoppable*

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Camoufox](https://img.shields.io/badge/Browser-Camoufox-orange.svg)](https://camoufox.com)

</div>

---

## Features

- 🦅 **Fast Detection** - Automatic sitekey detection from URLs
- 🛡️ **Anti-Fingerprint** - Uses Camoufox to avoid bot detection
- 🎯 **High Success Rate** - Intelligent mouse movement and timing
- 🔧 **Easy to Use** - Simple API, just provide URL
- 🌐 **REST API** - Built-in Flask server

## Installation

```bash
# Clone the repository
git clone https://github.com/your-username/alap-alap.git
cd alap-alap

# Install dependencies
pip install -e .

# Install Camoufox browser
camoufox fetch
```

## Quick Start

### Python API

```python
from alap_alap import AlapAlap

# Using context manager
with AlapAlap() as alap:
    result = alap.solve("https://example.com/login")
    
    if result["success"]:
        print(f"Token: {result['token']}")
        print(f"Sitekey: {result['sitekey']}")
        print(f"Time: {result['time']:.1f}s")
```

### REST API

```bash
# Start the server
python -m alap_alap.api.server

# Solve captcha
curl -X POST http://localhost:5000/solve \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/login", "invisible": true}'
```

## API Reference

### `AlapAlap`

Main class for captcha solving.

```python
AlapAlap(proxy=None, headless=True)
```

**Methods:**
- `solve(url, invisible=True)` - Solve captcha and return result dict
- `solve_with_sitekey(url, sitekey, invisible=True)` - Solve with known sitekey

## Response Format

```json
{
    "status": "success",
    "token": "0.your-captcha-token...",
    "sitekey": "0x4AAAAAAA...",
    "time": 2.5
}
```

## Requirements

- Python 3.8+
- Camoufox
- Playwright

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with 🦅 by Alap-Alap Team**

*Fast as a falcon, smart as a hunter*

</div>
