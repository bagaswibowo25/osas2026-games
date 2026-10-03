"""Prize admin for the booth games.

Serves the admin page and a tiny JSON API that reads/writes config/<game>.json,
the same files the game containers serve to the tablets. Standard library only.

  GET  /                   admin page
  GET  /api/config/<game>  current config
  PUT  /api/config/<game>  validate + save (atomic replace)

Every request needs HTTP Basic auth (user "admin", password ADMIN_PASSWORD).
"""

import base64
import hmac
import json
import os
import re
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
STATIC_DIR = Path(__file__).parent / "static"
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MAX_BODY = 16 * 1024

# Per game: the tier field that sets the condition, and whether it may be left empty.
GAMES = {
    "memory": {"key": "maxSeconds", "optional": True},
    "distro": {"key": "maxMistakes", "optional": True},
    "command": {"key": "minCorrect", "optional": False},
}

STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2"}


class Invalid(ValueError):
    pass


def _int(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise Invalid(f"{name} must be a whole number from {lo} to {hi}")
    return v


def _text(v, name):
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > 60:
        raise Invalid(f"{name} must be 1 to 60 characters")
    return v.strip()


def validate(game, data):
    """Return a clean config dict for `game`, or raise Invalid with a readable message."""
    if not isinstance(data, dict):
        raise Invalid("config must be a JSON object")
    rule = GAMES[game]
    seconds = _int(data.get("seconds"), "Duration", 10, 600)
    tiers = data.get("tiers")
    if not isinstance(tiers, list) or len(tiers) > 10:
        raise Invalid("tiers must be a list of at most 10 prizes")
    clean = []
    for i, t in enumerate(tiers, 1):
        if not isinstance(t, dict):
            raise Invalid(f"Tier {i} is not an object")
        tier = {"prize": _text(t.get("prize"), f"Tier {i} prize")}
        cond = t.get(rule["key"])
        if cond is None:
            if not rule["optional"]:
                raise Invalid(f"Tier {i} needs {rule['key']}")
        else:
            tier[rule["key"]] = _int(cond, f"Tier {i} {rule['key']}", 0, 1000)
        clean.append(tier)
    if game == "memory" and any(t.get("maxSeconds", 0) > seconds for t in clean):
        raise Invalid("maxSeconds cannot be longer than the game duration")
    return {"seconds": seconds, "tiers": clean, "fallback": _text(data.get("fallback"), "Fallback prize")}


def save(game, cfg):
    # Write to a temp file in the same directory, then rename: readers never see a half-written file.
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=f".{game}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, CONFIG_DIR / f"{game}.json")
    except BaseException:
        os.unlink(tmp)
        raise


class Handler(BaseHTTPRequestHandler):
    server_version = "booth-admin"

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode())

    def _authed(self):
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
            except ValueError:
                user, pw = "", ""
            if hmac.compare_digest(user, "admin") & hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                return True
            time.sleep(1)  # slow down guessing
        self._send(401, b"Login required\n", "text/plain", {"WWW-Authenticate": 'Basic realm="Booth prizes"'})
        return False

    def _game(self):
        m = re.fullmatch(r"/api/config/([a-z]+)", self.path)
        if not m or m.group(1) not in GAMES:
            self._json(404, {"error": "unknown game"})
            return None
        return m.group(1)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b"ok\n", "text/plain")
        if not self._authed():
            return
        if self.path.startswith("/api/"):
            game = self._game()
            if game:
                try:
                    self._json(200, json.loads((CONFIG_DIR / f"{game}.json").read_text()))
                except (OSError, ValueError) as e:
                    self._json(500, {"error": f"cannot read {game}.json: {e}"})
            return
        name = "index.html" if self.path in ("/", "/index.html") else self.path.lstrip("/")
        f = (STATIC_DIR / name).resolve()
        if STATIC_DIR.resolve() not in f.parents or not f.is_file():
            return self._send(404, b"Not found\n", "text/plain")
        self._send(200, f.read_bytes(), STATIC_TYPES.get(f.suffix, "application/octet-stream"))

    def do_PUT(self):
        if not self._authed():
            return
        game = self._game()
        if not game:
            return
        # JSON content type forces a CORS preflight, so other sites cannot submit this cross-origin.
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._json(415, {"error": "expected application/json"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "too large"})
        try:
            cfg = validate(game, json.loads(self.rfile.read(length)))
        except (ValueError, Invalid) as e:
            return self._json(400, {"error": str(e)})
        save(game, cfg)
        self.log_message("saved %s.json", game)
        self._json(200, cfg)


if __name__ == "__main__":
    if len(PASSWORD) < 8:
        raise SystemExit("ADMIN_PASSWORD must be set (8+ characters); see .env.example")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
