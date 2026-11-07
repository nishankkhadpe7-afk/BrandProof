"""Load backend/.env into os.environ (no extra dependency). Real env vars win."""
import os as _os

_env = _os.path.join(_os.path.dirname(__file__), "..", ".env")
if _os.path.exists(_env):
    with open(_env, encoding="utf-8-sig") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _v = _v.split(" #", 1)[0].strip().strip('"').strip("'")
            _os.environ.setdefault(_k.strip(), _v)
