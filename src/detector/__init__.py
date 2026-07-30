"""Detector module for Alap-Alap."""

from .sitekey_detector import (
    METHOD_DOM,
    METHOD_HTML,
    METHOD_JS_BUNDLE,
    METHOD_URL,
    SitekeyDetector,
)

__all__ = [
    "METHOD_DOM",
    "METHOD_HTML",
    "METHOD_JS_BUNDLE",
    "METHOD_URL",
    "SitekeyDetector",
]
