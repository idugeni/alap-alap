"""
Alap-Alap REST API Server

Flask-based REST API for the captcha solver.
"""

import time
from flask import Flask, request, jsonify
from loguru import logger


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    @app.route("/")
    def index():
        """API info."""
        return jsonify({
            "name": "Alap-Alap API",
            "version": "1.0.0",
            "endpoints": {
                "/solve": "POST - Solve captcha",
                "/detect": "POST - Detect sitekey",
                "/health": "GET - Health check",
                "/sitekeys": "GET - List sitekeys",
            }
        })

    @app.route("/health")
    def health():
        """Health check endpoint."""
        return jsonify({"status": "healthy", "service": "alap-alap"})

    @app.route("/detect", methods=["POST"])
    def detect():
        """
        Detect sitekey from URL.

        Request body:
            {"url": "https://example.com"}

        Response:
            {"success": true, "sitekey": "0x4AAAAAAA..."}
        """
        data = request.json

        if not data or "url" not in data:
            return jsonify({"success": False, "error": "URL is required"}), 400

        url = data["url"]

        try:
            from src.detector import SitekeyDetector
            detector = SitekeyDetector()
            sitekey = detector.detect(url)

            if sitekey:
                return jsonify({"success": True, "sitekey": sitekey})
            else:
                return jsonify({"success": False, "error": "Sitekey not found"})

        except Exception as e:
            logger.error(f"Detection error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/solve", methods=["POST"])
    def solve():
        """
        Solve Turnstile captcha.

        Request body:
            {
                "url": "https://example.com/login",
                "sitekey": "0x4AAAAAAA...",  // optional
                "proxy": "user:pass@host:port",  // optional
                "invisible": true  // optional
            }

        Response:
            {
                "success": true,
                "token": "0...",
                "sitekey": "0x4AAAAAAA...",
                "time": 1.23
            }
        """
        data = request.json

        if not data or "url" not in data:
            return jsonify({"success": False, "error": "URL is required"}), 400

        url = data["url"]
        sitekey = data.get("sitekey")
        proxy = data.get("proxy")
        invisible = data.get("invisible", True)

        try:
            from src.core import AlapAlap

            with AlapAlap(proxy=proxy) as alap:
                if sitekey:
                    result = alap.solve_with_sitekey(url, sitekey, invisible=invisible)
                else:
                    result = alap.solve(url, invisible=invisible)

            return jsonify(result)

        except Exception as e:
            logger.error(f"Solve error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/sitekeys")
    def sitekeys():
        """List all sitekeys in database."""
        from src.sitekeys_db import sitekeys_db

        entries = sitekeys_db.get_all()
        return jsonify({
            "count": len(entries),
            "sitekeys": [
                {
                    "sitekey": e.sitekey,
                    "platform": e.platform_name,
                    "domain": e.domain,
                    "status": e.status,
                    "solve_count": e.solve_count,
                    "success_count": e.success_count,
                }
                for e in entries
            ]
        })

    return app
