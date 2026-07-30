"""
Alap-Alap - Cloudflare Turnstile Captcha Solver

Entry point kept at the repository root so the documented
``python main.py <command>`` usage keeps working. The implementation lives in
:mod:`src.cli` so it ships inside the installed package and is covered by the
same lint, format and type checks as the rest of ``src/``.
"""

from src.cli import app

if __name__ == "__main__":
    app()
