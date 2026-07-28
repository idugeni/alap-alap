"""
API usage example for Alap-Alap.

This example demonstrates how to use the Alap-Alap REST API.
"""

import requests
import json


def main():
    """Main example function."""
    
    # API endpoint
    API_URL = "http://localhost:5000"
    
    # Example 1: Health check
    print("Example 1: Health check")
    print("-" * 40)
    
    try:
        response = requests.get(f"{API_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except requests.exceptions.ConnectionError:
        print("API server not running. Start with: python -m alap_alap.api.server")
    
    print()
    
    # Example 2: Solve captcha
    print("Example 2: Solve captcha")
    print("-" * 40)
    
    payload = {
        "url": "https://example.com/login",
        "invisible": True
    }
    
    try:
        response = requests.post(
            f"{API_URL}/solve",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✓ Token received!")
            print(f"  Token: {data['token'][:50]}...")
            print(f"  Time: {data['time']:.1f}s")
        
    except requests.exceptions.ConnectionError:
        print("API server not running. Start with: python -m alap_alap.api.server")
    
    print()
    
    # Example 3: With proxy
    print("Example 3: With proxy")
    print("-" * 40)
    
    payload = {
        "url": "https://example.com/login",
        "invisible": True,
        "proxy": "user:pass@proxy.example.com:8080"
    }
    
    try:
        response = requests.post(
            f"{API_URL}/solve",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
    except requests.exceptions.ConnectionError:
        print("API server not running. Start with: python -m alap_alap.api.server")


if __name__ == "__main__":
    main()
