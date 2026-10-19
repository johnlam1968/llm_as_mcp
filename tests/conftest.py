"""Shared pytest fixtures and environment setup for the llm_as_mcp test suite.

Critical: ``base.py`` reads the ``LLM_API_KEY_DICT`` environment variable at
import time and calls ``sys.exit(1)`` if it is missing. We therefore set the
variable here, at the very top of conftest.py, BEFORE any test module imports
``base`` (or transitively imports it via ``mcp_server`` -> ...).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrapping (must happen BEFORE any module under test is
# imported). pytest imports conftest.py before collecting test modules, so this
# block executes early enough.
# ---------------------------------------------------------------------------

# Tell base.py that a secret_dict is available. We use a small, deterministic
# JSON blob so that tests can reference known model names / api keys.
_DEFAULT_SECRET_DICT = {
    "test-model-1": "fake-api-key-1",
    "test-model-2": "fake-api-key-2",
    "gpt-4": "fake-openai-key",
}

os.environ.setdefault(
    "LLM_API_KEY_DICT",
    json.dumps(_DEFAULT_SECRET_DICT),
)

# Ensure the project root (where base.py and mcp_server.py live) is importable
# regardless of where pytest is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the project root (where base.py and mcp_server.py live)."""
    return _PROJECT_ROOT


@pytest.fixture(scope="session")
def base_module():
    """Imported ``base`` module.

    We import lazily inside the fixture so the env-var bootstrapping above has
    already taken effect. ``scope="session"`` avoids re-running the decorator
    on every test (which would just be wasted work; the module is the same).
    """
    # Drop any cached import so we definitely read the env var fresh.
    sys.modules.pop("base", None)
    return importlib.import_module("base")


@pytest.fixture(scope="session")
def mcp_server_module():
    """Imported ``mcp_server`` module.

    Imported lazily to ensure the project root is on ``sys.path`` and that any
    env-var side effects from importing ``base`` (there shouldn't be any beyond
    the decorator registration) have settled.
    """
    sys.modules.pop("mcp_server", None)
    return importlib.import_module("mcp_server")


@pytest.fixture
def secret_dict():
    """Return the canonical secret_dict used by base.py for these tests."""
    return dict(_DEFAULT_SECRET_DICT)


@pytest.fixture
def patched_secret_dict(base_module, monkeypatch):
    """Replace ``base.secret_dict`` for the duration of a single test.

    Useful for tests that want to exercise the "model not found in secret_dict"
    branch without disturbing other tests.
    """
    def _set(new_dict):
        monkeypatch.setattr(base_module, "secret_dict", new_dict)

    return _set


@pytest.fixture
def patched_openrouter_key(mcp_server_module, monkeypatch):
    """Replace the ``OPENROUTER_KEY`` module attribute for a single test.

    Lets us flip the value between "set" and "None"/"" without touching the
    real environment.
    """
    def _set(value):
        monkeypatch.setattr(mcp_server_module, "OPENROUTER_KEY", value)

    return _set
