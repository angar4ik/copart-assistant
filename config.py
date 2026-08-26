"""
Config helper — loads secrets from a local .env file (never committed).

.env format (see .env.example):
    COPART_EMAIL=you@example.com
    COPART_PASSWORD=yourpassword
    AUTO_DEV_API_KEY=sk_...

Values already set in the real environment take precedence over the .env file.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"
_loaded = False


def load_env():
    """Read .env into os.environ (does NOT override existing env vars)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get(key, default=None):
    """Return env var value, loading .env first."""
    load_env()
    return os.environ.get(key, default)


def require(key):
    """Return env var or raise a helpful error if missing."""
    val = get(key)
    if not val:
        raise SystemExit(
            "[error] Missing required env var '%s'. Copy .env.example to .env and fill it in."
            % key
        )
    return val
