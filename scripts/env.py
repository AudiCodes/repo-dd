"""API keys: from the environment, else from .env at the repo root."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def key(name):
    if os.environ.get(name):
        return os.environ[name]
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip():
                return v.strip().strip("'\"")
    raise SystemExit(f"{name} is not set: export it or add it to {path} (see .env.example)")
