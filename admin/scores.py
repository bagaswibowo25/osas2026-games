"""Leaderboard storage and the plausibility checks for submitted results.

Scores are computed in the browser, so the server cannot fully trust them.
What it can do: hand out a one-time token when a game starts, then reject
results that don't fit the time that actually passed (a 2-second Memory run,
50 answers in 30 seconds, ...). Good enough for a booth; staff can delete
anything odd from the admin page.

A player is identified by their Instagram username (unique, and what the crew
uses to reach winners). It is stored but never returned by the public API.
"""

import re
import secrets
import sqlite3
import threading
import time
import unicodedata

TOP_N = 10
NAME_MAX = 20
SLACK = 3            # seconds of network/clock slack allowed when comparing times
MAX_PENDING = 2000   # cap on outstanding start tokens


class Rejected(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY,
  game TEXT NOT NULL,
  name TEXT NOT NULL,
  ig TEXT NOT NULL,
  won INTEGER NOT NULL DEFAULT 0,
  matched INTEGER,
  moves INTEGER,
  mistakes INTEGER,
  used INTEGER,
  correct INTEGER,
  answered INTEGER,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS scores_game ON scores (game);
"""

# Sort key per game, lower is better; ties go to whoever got there first.
RANK = {
    "memory": lambda r: (-r["won"], -r["matched"], r["used"], r["moves"], r["created_at"]),
    "distro": lambda r: (-r["won"], -r["matched"], r["mistakes"], r["used"], r["created_at"]),
    "command": lambda r: (-r["correct"], r["answered"] - r["correct"], r["created_at"]),
}
PUBLIC_FIELDS = ("name", "won", "matched", "moves", "mistakes", "used", "correct", "answered")


def clean_name(raw):
    if not isinstance(raw, str):
        raise Rejected("Please enter your name")
    name = "".join(ch for ch in raw if unicodedata.category(ch)[0] != "C")
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        raise Rejected("Please enter your name")
    if len(name) > NAME_MAX:
        raise Rejected(f"Name can be at most {NAME_MAX} characters")
    return name


IG_RE = re.compile(r"[a-z0-9._]{1,30}")


def clean_ig(raw):
    ig = raw.strip().lstrip("@").lower() if isinstance(raw, str) else ""
    if not ig:
        raise Rejected("Please enter your Instagram username")
    if not IG_RE.fullmatch(ig):
        raise Rejected("Instagram username can only have letters, numbers, . and _ (max 30)")
    return ig


def _int(d, key, lo, hi):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise Rejected(f"bad {key}")
    return v


class Scores:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.pending = {}  # token -> (game, started_at, seconds)

    # --- game flow -------------------------------------------------------

    def start(self, game, seconds):
        now = time.time()
        with self.lock:
            for tok, (_, t0, secs) in list(self.pending.items()):
                if now - t0 > secs + 120:
                    del self.pending[tok]
            if len(self.pending) >= MAX_PENDING:
                raise Rejected("busy, try again")
            token = secrets.token_urlsafe(16)
            self.pending[token] = (game, now, seconds)
        return token

    def finish(self, game, body):
        token = body.get("token")
        with self.lock:
            entry = self.pending.pop(token, None) if isinstance(token, str) else None
        if not entry or entry[0] != game:
            raise Rejected("unknown or used game token")
        _, t0, seconds = entry
        elapsed = time.time() - t0
        name = clean_name(body.get("name"))
        ig = clean_ig(body.get("ig"))
        row = {"game": game, "name": name, "ig": ig, "won": 0, "matched": None, "moves": None,
               "mistakes": None, "used": None, "correct": None, "answered": None, "created_at": time.time()}
        timed_out = elapsed >= seconds - SLACK

        if game in ("memory", "distro"):
            row["matched"] = _int(body, "matched", 0, 6)
            row["won"] = int(row["matched"] == 6)
            if game == "memory":
                row["moves"] = _int(body, "moves", row["matched"], 500)
            else:
                row["mistakes"] = _int(body, "mistakes", 0, 500)
            if row["won"]:
                row["used"] = _int(body, "used", 0, seconds)
                if row["used"] > elapsed + SLACK or row["used"] < elapsed - SLACK - 2:
                    raise Rejected("time does not add up")
                if row["used"] < (5 if game == "memory" else 3):
                    raise Rejected("too fast")
            else:
                if not timed_out:
                    raise Rejected("game is not over yet")
                row["used"] = seconds
        else:  # command
            row["answered"] = _int(body, "answered", 0, 1000)
            row["correct"] = _int(body, "correct", 0, row["answered"])
            if not timed_out:
                raise Rejected("game is not over yet")
            if row["answered"] > (elapsed + 1) * 4:
                raise Rejected("too many answers")
        if elapsed > seconds + 60:
            raise Rejected("game took too long")

        with self.lock:
            cols = ", ".join(row)
            self.db.execute(f"INSERT INTO scores ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
            self.db.commit()
            board = self._board(game)
        rank = next(i for i, r in enumerate(board, 1) if r["ig"] == ig)
        return {"rank": rank, "players": len(board)}

    # --- reading ---------------------------------------------------------

    def _board(self, game):
        """Best result per player (Instagram username), best first. Call with the lock held."""
        rows = [dict(r) for r in self.db.execute("SELECT * FROM scores WHERE game = ?", (game,))]
        rows.sort(key=RANK[game])
        seen, best = set(), []
        for r in rows:
            if r["ig"] not in seen:
                seen.add(r["ig"])
                best.append(r)
        return best

    def leaderboard(self, games, limit=TOP_N, admin=False):
        with self.lock:
            out = {}
            for g in games:
                board = self._board(g)
                fields = PUBLIC_FIELDS + (("ig", "created_at") if admin else ())
                out[g] = {"players": len(board), "top": [{k: r[k] for k in fields} for r in board[:limit]]}
            return out

    # --- admin -----------------------------------------------------------

    def delete_player(self, game, ig):
        with self.lock:
            n = self.db.execute("DELETE FROM scores WHERE game = ? AND ig = ?", (game, ig)).rowcount
            self.db.commit()
        return n

    def reset(self):
        with self.lock:
            n = self.db.execute("DELETE FROM scores").rowcount
            self.db.commit()
        return n
