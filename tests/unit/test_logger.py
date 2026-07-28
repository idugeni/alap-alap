"""Unit tests for logger module."""

import os
import shutil
from pathlib import Path
from src.logger import setup_logger, clean_old_logs, get_log_stats
from src.config import config


class TestLogger:
    """Test logger functions."""

    def setup_method(self):
        """Create temp log directory."""
        self.test_log_dir = Path("test_logs")
        self.test_log_dir.mkdir(exist_ok=True)

    def teardown_method(self):
        """Cleanup temp log directory."""
        if self.test_log_dir.exists():
            shutil.rmtree(self.test_log_dir)

    def test_setup_logger(self):
        logger = setup_logger()
        assert logger is not None

    def test_get_log_stats(self):
        stats = get_log_stats()
        assert "files" in stats
        assert "total_size_mb" in stats
        assert isinstance(stats["files"], int)

    def test_clean_old_logs(self):
        # Create old log file
        old_file = self.test_log_dir / "old.log"
        old_file.write_text("old log content")

        clean_old_logs(self.test_log_dir, retention_days=0)

        # File should be deleted (0 days retention)
        # Note: current log file is skipped
