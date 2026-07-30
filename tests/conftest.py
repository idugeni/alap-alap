"""
Shared pytest configuration.

Storage paths are redirected to a temporary directory *before* any ``src``
module is imported. This matters because :data:`src.sitekeys_db.sitekeys_db` is
a module-level singleton built from ``config.storage.DATABASE_FILE`` at import
time, so a fixture would run too late: tests that exercise the API's solve path
would otherwise write ``captcha_database.json`` into the working tree.

pytest imports ``conftest.py`` before the test modules, which is what makes this
ordering work.
"""

import os
import shutil
import tempfile

# --------------------------------------------------------------------------- #
# Must run before `import src.*` anywhere in the test suite.
# --------------------------------------------------------------------------- #
_TEST_STORAGE = tempfile.mkdtemp(prefix="alap-tests-")

os.environ.setdefault(
    "ALAP_STORAGE_DATABASE_FILE", os.path.join(_TEST_STORAGE, "captcha_database.json")
)
os.environ.setdefault("ALAP_STORAGE_RESULTS_FILE", os.path.join(_TEST_STORAGE, "results.txt"))
os.environ.setdefault("ALAP_LOGGING_LOG_DIR", os.path.join(_TEST_STORAGE, "logs"))
# Keep tests from picking up a developer's alap-alap.yml in the repository root.
os.environ.setdefault("ALAP_CONFIG_FILE", "")

if not os.environ["ALAP_CONFIG_FILE"]:
    del os.environ["ALAP_CONFIG_FILE"]

import pytest  # noqa: E402  - deliberately after the environment setup


@pytest.fixture(scope="session", autouse=True)
def _clean_test_storage():
    """Remove the temporary storage directory when the session ends."""
    yield
    shutil.rmtree(_TEST_STORAGE, ignore_errors=True)


@pytest.fixture
def test_storage_dir():
    """Path to the session-wide temporary storage directory."""
    return _TEST_STORAGE
