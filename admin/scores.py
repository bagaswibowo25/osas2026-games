"""Leaderboard storage and the plausibility checks for submitted results.

Scores are computed in the browser, so the server cannot fully trust them.
What it can do: hand out a one-time token when a game starts, then reject
results that don't fit the time that actually passed (a 2-second Memory run,
50 answers in 30 seconds, ...). Good enough for a booth; staff can delete
anything odd from the admin page.

A player is identified by their Instagram username (unique, and what the crew
uses to reach winners). It is stored but never returned by the public API.

Turns: a player signs in once (name + Instagram) and gets MAX_PLAYS chances
across all games. Starting the second chance drops the first result. The
session closes when they take their prize or start their last chance; after
that neither the Instagram username nor the name can sign in again.
"""

import re
import secrets
import sqlite3
import threading
import time
import unicodedata

TOP_N = 10
PAIRS = {"memory": 6, "distro": 8}  # pairs to find for a finished round
NAME_MAX = 20
SLACK = 3            # seconds of network/clock slack allowed when comparing times
MAX_PENDING = 2000   # cap on outstanding start tokens
MAX_PLAYS = 2        # chances per player, across all games


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
CREATE INDEX IF NOT EXISTS scores_ig ON scores (ig);
CREATE TABLE IF NOT EXISTS players (
  ig TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  plays INTEGER NOT NULL DEFAULT 0,
  closed INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
"""
# Columns added to scores after the first deploy: which chance it was, whether a
# later chance dropped it, and the prize it earned (from the config at the time).
SCORE_COLUMNS = (("attempt", "INTEGER"), ("void", "INTEGER NOT NULL DEFAULT 0"), ("prize", "TEXT"))
RESULT_FIELDS = ("game", "won", "matched", "moves", "mistakes", "used", "correct", "answered", "prize")

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


def name_key(name):
    return name.casefold()


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
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(scores)")}
        for col, decl in SCORE_COLUMNS:
            if col not in have:
                self.db.execute(f"ALTER TABLE scores ADD COLUMN {col} {decl}")
        self.db.commit()
        self.pending = {}  # token -> (game, started_at, seconds, ig, attempt)

    # --- players ---------------------------------------------------------

    def _player(self, ig):
        return self.db.execute("SELECT * FROM players WHERE ig = ?", (ig,)).fetchone()

    def _result(self, ig):
        """The result that currently counts for this player, or None. Call with the lock held."""
        r = self.db.execute("SELECT * FROM scores WHERE ig = ? AND void = 0 ORDER BY id DESC LIMIT 1", (ig,)).fetchone()
        return {k: r[k] for k in RESULT_FIELDS} if r else None

    def _state(self, p):
        return {"name": p["name"], "ig": p["ig"], "plays": p["plays"],
                "left": 0 if p["closed"] else MAX_PLAYS - p["plays"], "result": self._result(p["ig"])}

    def register(self, raw_name, raw_ig):
        """Sign in a new player, or pick up an unfinished session (same Instagram)."""
        name, ig = clean_name(raw_name), clean_ig(raw_ig)
        with self.lock:
            p = self._player(ig)
            if p is None:
                if self.db.execute("SELECT 1 FROM players WHERE name_key = ?", (name_key(name),)).fetchone():
                    raise Rejected(f'The name "{name}" has already played. Add your last name or an initial.')
                self.db.execute("INSERT INTO players (ig, name, name_key, created_at) VALUES (?, ?, ?, ?)",
                                (ig, name, name_key(name), time.time()))
                self.db.commit()
                p = self._player(ig)
            elif p["closed"]:
                raise Rejected(f"@{ig} has already played. It is one turn per person.")
            return self._state(p)

    def close(self, raw_ig):
        """The player takes their prize: no more chances, and the name stays used."""
        ig = clean_ig(raw_ig)
        with self.lock:
            p = self._player(ig)
            if p is None:
                raise Rejected("unknown player")
            if p["plays"] < 1:
                raise Rejected("play a game first")
            self.db.execute("UPDATE players SET closed = 1 WHERE ig = ?", (ig,))
            self.db.commit()
        return {"closed": True}

    # --- game flow -------------------------------------------------------

    def start(self, game, seconds, raw_ig):
        ig = clean_ig(raw_ig)
        now = time.time()
        with self.lock:
            for tok, entry in list(self.pending.items()):
                if now - entry[1] > entry[2] + 120:
                    del self.pending[tok]
            if len(self.pending) >= MAX_PENDING:
                raise Rejected("busy, try again")
            p = self._player(ig)
            if p is None:
                raise Rejected("Please sign in with your name first")
            if p["closed"] or p["plays"] >= MAX_PLAYS:
                raise Rejected("No chances left. Thanks for playing!")
            attempt = p["plays"] + 1
            # The last chance closes the session right away, and any new chance drops earlier results.
            self.db.execute("UPDATE players SET plays = ?, closed = ? WHERE ig = ?",
                            (attempt, int(attempt >= MAX_PLAYS), ig))
            self.db.execute("UPDATE scores SET void = 1 WHERE ig = ? AND void = 0", (ig,))
            self.db.commit()
            token = secrets.token_urlsafe(16)
            self.pending[token] = (game, now, seconds, ig, attempt)
        return {"token": token, "attempt": attempt, "left": MAX_PLAYS - attempt}

    def finish(self, game, body, prize_for=lambda game, row: None):
        token = body.get("token")
        with self.lock:
            entry = self.pending.pop(token, None) if isinstance(token, str) else None
        if not entry or entry[0] != game:
            raise Rejected("unknown or used game token")
        _, t0, seconds, ig, attempt = entry
        elapsed = time.time() - t0
        with self.lock:
            p = self._player(ig)
        if p is None:
            raise Rejected("player was removed by the crew")
        row = {"game": game, "name": p["name"], "ig": ig, "won": 0, "matched": None, "moves": None,
               "mistakes": None, "used": None, "correct": None, "answered": None, "created_at": time.time(),
               "attempt": attempt, "void": 0, "prize": None}
        timed_out = elapsed >= seconds - SLACK

        if game in ("memory", "distro"):
            row["matched"] = _int(body, "matched", 0, PAIRS[game])
            row["won"] = int(row["matched"] == PAIRS[game])
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
        row["prize"] = prize_for(game, row)

        with self.lock:
            # A later chance already started (should not happen from the tablet): keep it, but dropped.
            p = self._player(ig)
            row["void"] = int(p is None or attempt < p["plays"])
            cols = ", ".join(row)
            self.db.execute(f"INSERT INTO scores ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
            self.db.commit()
            board = self._board(game)
            left = 0 if p is None or p["closed"] else MAX_PLAYS - p["plays"]
        rank = next((i for i, r in enumerate(board, 1) if r["ig"] == ig), None)
        return {"rank": rank, "players": len(board), "prize": row["prize"], "attempt": attempt, "left": left}

    # --- reading ---------------------------------------------------------

    def _board(self, game):
        """Best result per player (Instagram username), best first. Call with the lock held."""
        rows = [dict(r) for r in self.db.execute("SELECT * FROM scores WHERE game = ? AND void = 0", (game,))]
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

    def players(self):
        """Every signed-in player, newest first, with the result that currently counts."""
        with self.lock:
            out = []
            for p in self.db.execute("SELECT * FROM players ORDER BY created_at DESC").fetchall():
                out.append({"name": p["name"], "ig": p["ig"], "plays": p["plays"], "closed": bool(p["closed"]),
                            "created_at": p["created_at"], "result": self._result(p["ig"])})
            return {"max_plays": MAX_PLAYS, "players": out}

    def allow_again(self, ig):
        """Forget a player entirely (all results, name freed) so they can sign in again."""
        with self.lock:
            n = self.db.execute("DELETE FROM scores WHERE ig = ?", (ig,)).rowcount
            p = self.db.execute("DELETE FROM players WHERE ig = ?", (ig,)).rowcount
            self.db.commit()
        return {"players": p, "results": n}

    def delete_player(self, game, ig):
        with self.lock:
            n = self.db.execute("DELETE FROM scores WHERE game = ? AND ig = ?", (game, ig)).rowcount
            self.db.commit()
        return n

    def reset(self):
        with self.lock:
            n = self.db.execute("DELETE FROM scores").rowcount
            self.db.execute("DELETE FROM players")
            self.db.commit()
        return n
