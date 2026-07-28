"""
Alap-Alap Logger

Smart logging with auto-cleaner for old logs.
"""

import os
import sys
import glob
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from src.config import config


def setup_logger():
    """Configure loguru with rotation and cleanup."""
    cfg = config.logging

    # Remove default handler
    logger.remove()

    # Create log directory
    log_dir = Path(cfg.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    # Console handler
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | {message}",
        level=cfg.LOG_LEVEL,
        colorize=True
    )

    # File handler with rotation
    log_path = log_dir / cfg.LOG_FILE
    logger.add(
        str(log_path),
        format=cfg.LOG_FORMAT,
        level="DEBUG",
        rotation=cfg.LOG_ROTATION,
        retention=cfg.LOG_RETENTION_DAYS,
        compression=cfg.LOG_COMPRESSION,
        encoding="utf-8"
    )

    # Clean old logs on startup
    clean_old_logs(log_dir, cfg.LOG_RETENTION_DAYS)

    logger.debug(f"Logger initialized: {log_path}")
    return logger


def clean_old_logs(log_dir: Path, retention_days: int):
    """Remove log files older than retention period."""
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0

    for log_file in log_dir.glob("*.log*"):
        try:
            # Skip current log
            if log_file.name == config.logging.LOG_FILE:
                continue

            # Check modification time
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                log_file.unlink()
                removed += 1
        except Exception:
            pass

    if removed:
        logger.debug(f"Cleaned {removed} old log files")


def get_log_stats():
    """Get log directory statistics."""
    log_dir = Path(config.logging.LOG_DIR)

    if not log_dir.exists():
        return {"files": 0, "total_size_mb": 0}

    files = list(log_dir.glob("*.log*"))
    total_size = sum(f.stat().st_size for f in files)

    return {
        "files": len(files),
        "total_size_mb": round(total_size / (1024 * 1024), 2)
    }


# Initialize logger on import
setup_logger()
