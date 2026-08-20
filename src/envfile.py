"""Minimal .env loader (stdlib only, no dependency).

Reads <project root>/.env if present and sets os.environ for any key
that isn't already set, so locally-run servers pick up secrets from the
gitignored .env file. On Render the values come from the dashboard env
vars instead, which always win.
"""
import os
from pathlib import Path


def load_dotenv(path=None):
    if not path:
        path = Path(__file__).resolve().parent.parent / ".env"
    path = Path(path)
    if not path.exists():
        return False
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return True