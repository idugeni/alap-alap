"""
Alap-Alap - Cloudflare Turnstile Captcha Solver

Main entry point for the application.
"""

import sys
from src.core import AlapAlap


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <url> [--sitekey <key>] [--proxy <proxy>] [--visible]")
        print("\nExamples:")
        print("  python main.py https://example.com/login")
        print("  python main.py https://example.com/login --sitekey 0x4AAAAAAAQV1p8gT2jN3m4")
        print("  python main.py https://example.com/login --proxy user:pass@host:port")
        sys.exit(1)

    url = sys.argv[1]
    sitekey = None
    proxy = None
    visible = False

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--sitekey" and i + 1 < len(args):
            sitekey = args[i + 1]
            i += 2
        elif args[i] == "--proxy" and i + 1 < len(args):
            proxy = args[i + 1]
            i += 2
        elif args[i] == "--visible":
            visible = True
            i += 1
        else:
            i += 1

    with AlapAlap(proxy=proxy) as alap:
        if sitekey:
            result = alap.solve_with_sitekey(url, sitekey, invisible=not visible)
        else:
            result = alap.solve(url, invisible=not visible)

        if result["success"]:
            print(f"✓ Success!")
            print(f"  Token: {result['token'][:50]}...")
            print(f"  Sitekey: {result['sitekey']}")
            print(f"  Time: {result['time']:.1f}s")
        else:
            print(f"✗ Failed: {result['error']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
