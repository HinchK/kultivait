"""Shared pytest setup.

Unit tests must make zero outbound network calls. `server.py` runs
`load_dotenv()` at import, which loads `.env`'s `POSTHOG_PROJECT_TOKEN` into the
environment; `build_app` then creates a live PostHog client that connects to
us.i.posthog.com on every request. Strip the telemetry env vars for the whole
session so `build_app` creates no client and the suite stays hermetic.

Session-scoped and autouse: it runs after collection has imported the modules
(so after `load_dotenv` has populated the environment), then removes the vars
before any test calls `build_app`.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _disable_telemetry():
    for var in ("POSTHOG_PROJECT_TOKEN", "POSTHOG_HOST"):
        os.environ.pop(var, None)
    yield
