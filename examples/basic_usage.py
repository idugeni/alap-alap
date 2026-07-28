"""
Basic usage example for Alap-Alap.

This example demonstrates how to use Alap-Alap to solve
Cloudflare Turnstile captchas.
"""

from alap_alap import AlapAlap


def main():
    """Main example function."""
    
    # Example 1: Basic usage with context manager
    print("Example 1: Basic usage")
    print("-" * 40)
    
    with AlapAlap() as alap:
        result = alap.solve("https://example.com/login")
        
        if result["success"]:
            print(f"✓ Success!")
            print(f"  Token: {result['token'][:50]}...")
            print(f"  Sitekey: {result['sitekey']}")
            print(f"  Time: {result['time']:.1f}s")
        else:
            print(f"✗ Failed: {result['error']}")
    
    print()
    
    # Example 2: With proxy
    print("Example 2: With proxy")
    print("-" * 40)
    
    proxy = "user:pass@proxy.example.com:8080"
    
    with AlapAlap(proxy=proxy) as alap:
        result = alap.solve("https://example.com/login")
        
        if result["success"]:
            print(f"✓ Success with proxy!")
            print(f"  Token: {result['token'][:50]}...")
        else:
            print(f"✗ Failed: {result['error']}")
    
    print()
    
    # Example 3: With known sitekey
    print("Example 3: With known sitekey")
    print("-" * 40)
    
    sitekey = "0x4AAAAAAAQV1p8gT2jN3m4"
    
    with AlapAlap() as alap:
        result = alap.solve_with_sitekey(
            "https://example.com/login",
            sitekey
        )
        
        if result["success"]:
            print(f"✓ Success with sitekey!")
            print(f"  Token: {result['token'][:50]}...")
        else:
            print(f"✗ Failed: {result['error']}")


if __name__ == "__main__":
    main()
