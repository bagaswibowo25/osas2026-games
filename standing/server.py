"""Last Geeko Standing: a live elimination game for the main hall.

Five rounds of three items each. Quiz rounds ask true/false questions, game rounds play three
mini games on the phone (Color Rush, Reflex, Odd Geeko Out, Bug Squash, Geeko Simon, Geeko Dash). Items inside a round follow each
other automatically; at the end of a round the best players by round score go through (a share
of the field, or a fixed number) and the host moves on by hand. The final round leaves 5 winners,
announced one by one.

One process holds the whole game in memory and snapshots it to /data, so a restart resumes.
Players and the host each talk to it over one WebSocket.

  GET /            player page (join with a name, then play on the phone)
  GET /host        host page: projector view + controls (ADMIN_PASSWORD)
  GET /qr.svg      QR code of the player URL
  GET /ws          WebSocket

Players can only join while the game is open: /games/admin writes {"open": true|false}
to config/last-geeko-standing.json. Rounds and questions live in
config/last-geeko-standing-questions.json.
"""

import asyncio
import hmac
import io
import json
import logging
import math
import os
import secrets
import tempfile
import time
from pathlib import Path

import segno
from aiohttp import WSMsgType, web

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
STATIC_DIR = Path(__file__).parent / "static"
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://quiz.opensuse.id/games/last-geeko-standing/")
LOCK_FILE = CONFIG_DIR / "last-geeko-standing.json"
QUESTIONS_FILE = CONFIG_DIR / "last-geeko-standing-questions.json"
STATE_FILE = DATA_DIR / "last-geeko-standing.json"

GRACE = 1.0  # seconds after a deadline in which answers still count (network delay)
MIN_MS = 150  # faster than this is not a human reaction
MAX_NAME = 20
WINNERS = 5
PODIUM_STEP = 3.0  # seconds between winner names
COUNTDOWN = 4.5  # "3, 2, 1, START!" before every round

# Mini games: how long the phone plays them (after the intro), per level
GAMES = {
    "color": {"title": "Geeko Color Rush", "seconds": {1: 20, 2: 20},
              "rule": "Tap the Geeko with the COLOR of the word, not what the word says."},
    "reflex": {"title": "Geeko Reflex", "seconds": {1: 20, 2: 20},
               "rule": "Tap the GREEN Geeko as fast as you can while it blinks. Red or orange Geeko = trap! Some run away."},
    "odd": {"title": "Odd Geeko Out", "seconds": {1: 25, 2: 25},
            "rule": "One Geeko is different. Find it, again and again. Wrong taps freeze you for a second."},
    "sort": {"title": "Geeko Sort", "seconds": {1: 25, 2: 25},
             "rule": "Drag each Geeko into the jar of its colour. Wrong jar = it jumps back."},
    "bug": {"title": "Bug Squash", "seconds": {1: 22, 2: 22},
            "rule": "Squash the bugs as they pop up. Don't tap the Geeko!"},
    "simon": {"title": "Geeko Simon", "seconds": {1: 30, 2: 30},
              "rule": "Watch the Geeko light up, then tap them in the same order. It gets longer every time."},
    "dash": {"title": "Geeko Dash", "seconds": {1: 20, 2: 20},
             "rule": "Swipe the way the Geeko looks. RED Geeko: swipe the OPPOSITE way!"},
}
GAME_ORDER = ["color", "reflex", "sort"]

log = logging.getLogger("standing")


def load_config():
    data = json.loads(QUESTIONS_FILE.read_text())
    cfg = {
        "intro_seconds": int(data.get("intro_seconds", 6)),
        "reveal_seconds": int(data.get("reveal_seconds", 4)),
        "rounds": [],
    }
    for i, r in enumerate(data["rounds"], 1):
        kind = r["type"]
        keep = r["keep"]
        if not (isinstance(keep, int) and keep >= 1) and not (isinstance(keep, float) and 0 < keep < 1):
            raise ValueError(f"round {i}: keep must be a share (0.5) or a number of players (10)")
        rd = {"title": str(r.get("title", f"Round {i}")), "type": kind, "keep": keep}
        if kind == "quiz":
            rd["seconds"] = int(r.get("seconds", 10))
            rd["items"] = [{"kind": "question", "text": str(q["text"]), "answer": bool(q["answer"])}
                           for q in r["questions"]]
        elif kind == "games":
            level = int(r.get("level", 1))
            names = r.get("games", GAME_ORDER)
            if any(g not in GAMES for g in names):
                raise ValueError(f"round {i}: games must be among {list(GAMES)}")
            rd["items"] = [{"kind": "game", "game": g, "level": level} for g in names]
        else:
            raise ValueError(f"round {i}: type must be quiz or games")
        if not rd["items"]:
            raise ValueError(f"round {i} has no items")
        cfg["rounds"].append(rd)
    if not cfg["rounds"]:
        raise ValueError("no rounds")
    return cfg


_lock_cache = {"at": 0.0, "open": False}


def is_open():
    """Whether players may join; cached for 2 s so 300 joins don't each read the file."""
    now = time.monotonic()
    if now - _lock_cache["at"] > 2:
        try:
            _lock_cache["open"] = bool(json.loads(LOCK_FILE.read_text()).get("open"))
        except (OSError, ValueError):
            _lock_cache["open"] = False
        _lock_cache["at"] = now
    return _lock_cache["open"]


def clean_name(raw):
    if not isinstance(raw, str):
        return None
    name = " ".join(raw.split())
    return name if 1 <= len(name) <= MAX_NAME else None


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def game_result(game, level, data, seconds):
    """Validate a mini game result from the phone. Returns (raw, better_is_higher, tiebreak_ms, label) or None.

    Phones play the games locally (same seed for everyone), so the server only checks that the
    numbers are humanly possible.
    """
    if game == "color":
        c, w = data.get("correct"), data.get("wrong")
        if not (_int(c, 0, seconds * 3) and _int(w, 0, seconds * 4)):
            return None
        return c - w, True, 0, f"{c} right, {w} wrong"
    if game == "reflex":
        h, w, avg = data.get("hits"), data.get("wrong"), data.get("avg")
        if not (_int(h, 0, seconds * 2) and _int(w, 0, seconds * 5) and _int(avg, 0, 3000)):
            return None
        if h and avg < 120:  # faster than humanly possible on average
            return None
        avg = avg if h else 3000
        label = f"{h} caught" + (f", {avg} ms" if h else "") + (f", {w} wrong" if w else "")
        return (h - w) * 1_000_000 - avg, True, avg, label
    if game == "bug":
        h, mi = data.get("hits"), data.get("misses")
        if not (_int(h, 0, seconds * 3) and _int(mi, 0, seconds * 3)):
            return None
        return h - 2 * mi, True, 0, f"{h} squashed" + (f", {mi} Geeko hit" if mi else "")
    if game == "simon":
        lv, ms = data.get("level"), data.get("ms")
        if not (_int(lv, 0, 25) and _int(ms, 0, (seconds + 5) * 1000)):
            return None
        return lv * 1_000_000 - ms, True, ms, f"{lv} in a row" if lv else "no sequence"
    if game == "dash":
        c, w = data.get("correct"), data.get("wrong")
        if not (_int(c, 0, seconds * 3) and _int(w, 0, seconds * 4)):
            return None
        return c - w, True, 0, f"{c} right, {w} wrong"
    if game == "sort":
        c, w, ms = data.get("sorted"), data.get("wrong"), data.get("ms")
        if not (_int(c, 0, seconds * 3) and _int(w, 0, seconds * 4) and _int(ms, 0, (seconds + 5) * 1000)):
            return None
        return (c - w) * 1_000_000 - ms, True, ms, f"{c} sorted" + (f", {w} wrong" if w else "")
    if game == "odd":
        lv, ms = data.get("levels"), data.get("ms")
        if not (_int(lv, 0, int(seconds * 2.5)) and _int(ms, 0, (seconds + 5) * 1000)):
            return None
        return lv * 1_000_000 - ms, True, ms, f"{lv} found"
    return None


class Game:
    def __init__(self):
        self.sockets = {}  # token -> set of player WebSockets
        self.hosts = set()
        self.timer = None
        self.progress_task = None
        self._save_pending = False
        self.reset()

    # ----- state -------------------------------------------------------------
    def reset(self):
        self.cancel_timer()
        self.game_id = secrets.token_hex(6)
        self.phase = "lobby"  # lobby countdown intro play reveal cut final_wait podium
        self.cfg = None
        self.r = -1  # round index
        self.i = -1  # item index inside the round
        self.players = {}  # token -> player dict
        self.order = []  # tokens in join order (field layout on the projector)
        self.names = {}  # lower-case name -> token
        self.started_at = 0.0
        self.deadline = 0.0
        self.next_action = ""
        self.seed = 0
        self.results = {}  # token -> result of the current item
        self.item_info = {}  # what the reveal shows for the current item
        self.cut = {}
        self.podium = []  # [{name, score}], 1st place first
        self.revealed = 0

    def snapshot(self):
        keys = ("game_id", "phase", "cfg", "r", "i", "players", "order", "started_at", "deadline",
                "next_action", "seed", "results", "item_info", "cut", "podium", "revealed")
        return {k: getattr(self, k) for k in keys}

    def save(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".standing.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(self.snapshot(), f)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log.warning("cannot save state: %s", e)

    def save_soon(self):
        """Answers arrive in bursts: write them at most twice a second instead of 300 times."""
        if self._save_pending:
            return
        self._save_pending = True

        def run():
            self._save_pending = False
            self.save()

        asyncio.get_running_loop().call_later(0.5, run)

    def restore(self):
        try:
            data = json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            return
        if "r" not in data:  # snapshot from the old single-question format
            return
        for k, v in data.items():
            setattr(self, k, v)
        self.names = {p["name"].lower(): t for t, p in self.players.items()}
        log.info("restored game %s: phase %s, round %s item %s, %d players", self.game_id, self.phase,
                 self.r + 1, self.i + 1, len(self.players))
        if self.next_action:
            self.schedule(max(0.5, self.deadline - time.time()), getattr(self, self.next_action))

    # ----- helpers -----------------------------------------------------------
    def alive(self):
        return [t for t in self.order if self.players[t]["out"] == 0]

    def rnd(self):
        return self.cfg["rounds"][self.r]

    def item(self):
        return self.rnd()["items"][self.i]

    def play_seconds(self):
        it = self.item()
        if it["kind"] == "question":
            return self.rnd()["seconds"]
        return GAMES[it["game"]]["seconds"][it["level"]]

    def schedule(self, delay, fn):
        self.cancel_timer()
        self.next_action = fn.__name__
        self.timer = asyncio.get_running_loop().call_later(delay, lambda: asyncio.ensure_future(fn()))

    def cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.next_action = ""

    def keep_count(self, n_alive):
        keep = self.rnd()["keep"]
        if self.r == len(self.cfg["rounds"]) - 1:
            return min(n_alive, WINNERS)
        n = keep if isinstance(keep, int) else math.ceil(n_alive * keep)
        # Never cut below what the last round needs
        return max(min(n, n_alive), min(n_alive, WINNERS))

    def standings(self):
        """Alive players by round score (higher first), ties broken by less time used."""
        alive = self.alive()
        return sorted(alive, key=lambda t: (-self.players[t]["score"], self.players[t]["tb"], self.order.index(t)))

    def submitted_count(self):
        return sum(1 for t in self.alive() if t in self.results)

    # ----- flow --------------------------------------------------------------
    async def start(self):
        if self.phase != "lobby" or not self.players:
            return
        self.cfg = load_config()
        await self.countdown(0)

    async def countdown(self, r):
        """3, 2, 1, START! on every screen before a round begins."""
        self.phase = "countdown"
        self.r, self.i = r, -1
        self.deadline = time.time() + COUNTDOWN
        self.schedule(COUNTDOWN, self.begin_round)
        self.save()
        await self.broadcast()

    async def begin_round(self):
        if self.phase == "countdown":
            await self.start_round(self.r)

    async def start_round(self, r):
        self.r, self.i = r, -1
        for t in self.alive():
            p = self.players[t]
            p["score"], p["tb"], p["last"] = 0, 0, None
        await self.next_item()

    async def next_item(self):
        self.i += 1
        self.results = {}
        self.item_info = {}
        self.seed = secrets.randbits(31)
        for p in self.players.values():
            p["last"] = None
        if self.item()["kind"] == "game":
            # Players need a moment to read the rules of a mini game
            self.phase = "intro"
            self.deadline = time.time() + self.cfg["intro_seconds"]
            self.schedule(self.cfg["intro_seconds"], self.begin_play)
            self.save()
            await self.broadcast()
        else:
            await self.begin_play()

    async def begin_play(self):
        self.phase = "play"
        self.started_at = time.time()
        self.deadline = self.started_at + self.play_seconds()
        self.schedule(self.play_seconds() + GRACE, self.end_play)
        self.save()
        await self.broadcast()
        self.start_progress()

    def start_progress(self):
        """While an item runs, tell the host how many players are done (at most ~3x a second)."""
        if self.progress_task and not self.progress_task.done():
            return

        async def loop():
            last = -1
            while self.phase == "play":
                n = self.submitted_count()
                if n != last:
                    last = n
                    await self.send_hosts({"t": "progress", "done": n})
                await asyncio.sleep(0.3)

        self.progress_task = asyncio.ensure_future(loop())

    def reaction_ms(self, ms, now):
        """The phone measures the time (fair on slow networks); keep it within what is possible."""
        server_ms = int((now - self.started_at) * 1000)
        if isinstance(ms, (int, float)) and not isinstance(ms, bool) and MIN_MS <= ms <= server_ms + 1000:
            return int(ms)
        return max(MIN_MS, server_ms)

    async def submit(self, token, data):
        p = self.players.get(token)
        if self.phase != "play" or not p or p["out"] or token in self.results:
            return
        if data.get("round") != self.r or data.get("item") != self.i:
            return
        now = time.time()
        if now > self.deadline + GRACE:
            return
        it = self.item()
        if it["kind"] == "question":
            if not isinstance(data.get("choice"), bool):
                return
            self.results[token] = {"choice": data["choice"], "ms": self.reaction_ms(data.get("ms"), now)}
        else:
            res = game_result(it["game"], it["level"], data, self.play_seconds())
            if res is None:
                log.info("rejected %s result from %s: %s", it["game"], p["name"], data)
                return
            raw, _, tb, label = res
            self.results[token] = {"raw": raw, "tb": tb, "label": label}
        self.save_soon()
        await self.send_player(token)
        if self.submitted_count() == len(self.alive()):
            self.schedule(0.6, self.end_play)

    async def end_play(self):
        if self.phase != "play":
            return
        self.cancel_timer()
        it = self.item()
        alive = self.alive()
        if it["kind"] == "question":
            limit_ms = self.play_seconds() * 1000
            right = 0
            for t in alive:
                p, res = self.players[t], self.results.get(t)
                ok = res is not None and res["choice"] == it["answer"]
                pts = 500 + int(500 * max(0.0, 1 - res["ms"] / limit_ms)) if ok else 0
                right += ok
                p["score"] += pts
                p["tb"] += res["ms"] if res else limit_ms
                p["last"] = {"points": pts, "correct": ok, "answered": res is not None}
            self.item_info = {"answer": it["answer"], "right": right, "total": len(alive)}
        else:
            # Points by rank in this mini game: best gets 1000, the rest spread down to ~0
            played = sorted((t for t in alive if t in self.results),
                            key=lambda t: (-self.results[t]["raw"], self.results[t]["tb"]))
            n = len(played)
            pts_of = {}
            for k, t in enumerate(played):
                pts_of[t] = round(1000 * (n - k) / n)
            for t in alive:
                p, res = self.players[t], self.results.get(t)
                pts = pts_of.get(t, 0)
                p["score"] += pts
                p["tb"] += res["tb"] if res else 60000
                p["last"] = {"points": pts, "label": res["label"] if res else "did not play",
                             "place": played.index(t) + 1 if t in pts_of else 0, "of": n}
            self.item_info = {"top": [{"name": self.players[t]["name"], "label": self.results[t]["label"]}
                                      for t in played[:5]], "played": n}
        self.rank_now()
        last_item = self.i == len(self.rnd()["items"]) - 1
        self.phase = "reveal"
        self.deadline = time.time() + self.cfg["reveal_seconds"]
        self.schedule(self.cfg["reveal_seconds"], self.end_round if last_item else self.next_item)
        self.save()
        await self.broadcast()

    def rank_now(self):
        for k, t in enumerate(self.standings(), 1):
            self.players[t]["rank"] = k

    async def end_round(self):
        if self.phase != "reveal":
            return
        self.cancel_timer()
        order = self.standings()
        keep = self.keep_count(len(order))
        final = self.r == len(self.cfg["rounds"]) - 1
        for k, t in enumerate(order, 1):
            p = self.players[t]
            p["rank"] = k
            if k > keep:
                p["out"] = self.r + 1
                p["reason"] = "cut"
                p["place"] = k
        self.cut = {"prev": len(order), "now": keep,
                    "top": [{"name": self.players[t]["name"], "score": self.players[t]["score"]} for t in order[:5]]}
        if final:
            self.podium = [{"name": self.players[t]["name"], "score": self.players[t]["score"]} for t in order[:keep]]
            self.phase = "final_wait"
        else:
            self.phase = "cut"
        self.save()
        await self.broadcast()

    async def advance(self):
        """Host pressed Next round after the cut."""
        if self.phase == "cut":
            await self.countdown(self.r + 1)

    async def show_winners(self):
        if self.phase != "final_wait":
            return
        self.phase = "podium"
        self.revealed = 0
        await self.podium_step()

    async def podium_step(self):
        """Names appear from 5th place up to the winner."""
        if self.phase != "podium" or self.revealed >= len(self.podium):
            return
        self.revealed += 1
        if self.revealed < len(self.podium):
            self.deadline = time.time() + PODIUM_STEP
            self.schedule(PODIUM_STEP, self.podium_step)
        else:
            self.cancel_timer()
        self.save()
        await self.broadcast()

    async def skip(self):
        if self.phase == "countdown":
            await self.begin_round()
        elif self.phase == "intro":
            await self.begin_play()
        elif self.phase == "play":
            await self.end_play()
        elif self.phase == "reveal":
            last_item = self.i == len(self.rnd()["items"]) - 1
            await (self.end_round() if last_item else self.next_item())

    # ----- players -----------------------------------------------------------
    async def join(self, ws, raw_name):
        if self.phase != "lobby":
            return {"t": "error", "code": "started"}
        if not is_open():
            return {"t": "error", "code": "locked"}
        name = clean_name(raw_name)
        if not name:
            return {"t": "error", "code": "bad_name"}
        if name.lower() in self.names:
            return {"t": "error", "code": "name_taken"}
        token = secrets.token_urlsafe(16)
        self.players[token] = {"name": name, "out": 0, "reason": "", "score": 0, "tb": 0, "rank": 0,
                               "place": 0, "last": None}
        self.order.append(token)
        self.names[name.lower()] = token
        self.sockets.setdefault(token, set()).add(ws)
        self.save_soon()
        await self.send_hosts(self.host_state())
        return {"t": "joined", "token": token, "game_id": self.game_id, "name": name}

    async def kick(self, name):
        token = self.names.get(str(name).lower())
        if not token or self.phase != "lobby":
            return
        self.names.pop(str(name).lower())
        self.players.pop(token, None)
        self.order.remove(token)
        for ws in self.sockets.pop(token, set()):
            await safe_send(ws, {"t": "kicked"})
        self.save()
        await self.send_hosts(self.host_state())

    async def leave(self, token):
        """Player chose Leave game. In the lobby the name is freed; once started they are out for good."""
        p = self.players.get(token)
        if not p:
            return
        socks = self.sockets.pop(token, set())
        if self.phase == "lobby":
            self.players.pop(token)
            self.order.remove(token)
            self.names.pop(p["name"].lower(), None)
        elif p["out"] == 0:
            p["out"], p["reason"] = self.r + 1, "left"
        for ws in socks:
            await safe_send(ws, {"t": "left"})
        self.save()
        await self.send_hosts(self.host_state())
        if self.phase == "play" and self.alive() and self.submitted_count() == len(self.alive()):
            self.schedule(0.6, self.end_play)

    # ----- what each screen gets ----------------------------------------------
    def common(self, s):
        s.update({"game_id": self.game_id, "phase": self.phase})
        if self.cfg is None or self.r < 0:
            return s
        rd = self.rnd()
        s["round"] = {"index": self.r, "count": len(self.cfg["rounds"]), "title": rd["title"], "type": rd["type"],
                      "item": self.i, "items": len(rd["items"]), "final": self.r == len(self.cfg["rounds"]) - 1}
        if self.phase in ("intro", "play", "reveal") and self.i >= 0:
            it = self.item()
            info = {"kind": it["kind"], "ends_in_ms": max(0, int((self.deadline - time.time()) * 1000))}
            if it["kind"] == "question":
                info.update({"text": it["text"], "limit_ms": self.play_seconds() * 1000})
            else:
                g = GAMES[it["game"]]
                info.update({"game": it["game"], "level": it["level"], "title": g["title"], "rule": g["rule"],
                             "limit_ms": self.play_seconds() * 1000})
                if self.phase != "intro":
                    info["seed"] = self.seed
            if self.phase == "intro":
                info["limit_ms"] = self.cfg["intro_seconds"] * 1000
            if self.phase == "reveal":
                info.update(self.item_info)
                info["limit_ms"] = self.cfg["reveal_seconds"] * 1000
            s["item"] = info
        if self.phase == "countdown":
            s["count_ms"] = max(0, int((self.deadline - time.time()) * 1000))
            s["count_total_ms"] = int(COUNTDOWN * 1000)
        if self.phase in ("cut", "final_wait"):
            s["cut"] = self.cut
        if self.phase == "podium":
            n = len(self.podium)
            # Shown from last place up: with 5 winners and 2 revealed, places 5 and 4 are known
            s["podium"] = [dict(w, place=k + 1) for k, w in enumerate(self.podium) if k >= n - self.revealed]
            s["podium_size"] = n
        return s

    def player_state(self, token):
        p = self.players[token]
        alive = self.alive()
        s = self.common({"t": "state", "alive": len(alive), "total": len(self.players)})
        you = {"name": p["name"], "out": p["out"], "reason": p["reason"], "score": p["score"],
               "rank": p["rank"], "place": p["place"], "last": p["last"], "done": token in self.results}
        if token in self.results and self.phase == "play":
            you["result"] = self.results[token]
        if self.cfg and self.r >= 0 and p["out"] == 0:
            you["keep"] = self.keep_count(len(alive))
        if self.phase == "podium":
            places = [w["name"] for w in self.podium]
            if p["name"] in places:
                you["win_place"] = places.index(p["name"]) + 1
        s["you"] = you
        return s

    def host_state(self):
        s = self.common({"t": "host_state", "alive": len(self.alive()), "total": len(self.players),
                         "open": is_open(), "url": PUBLIC_URL, "done": self.submitted_count(),
                         "field": [[self.players[t]["name"], self.players[t]["out"]] for t in self.order]})
        if self.cfg and self.r >= 0 and self.phase in ("play", "reveal", "intro"):
            s["keep"] = self.keep_count(len(self.alive()))
            s["leaders"] = [{"name": self.players[t]["name"], "score": self.players[t]["score"]}
                            for t in self.standings()[:5]] if self.phase == "reveal" else []
        return s

    # ----- sending -----------------------------------------------------------
    async def send_player(self, token):
        if token in self.players:
            msg = json.dumps(self.player_state(token))
            for ws in list(self.sockets.get(token, ())):
                await safe_send(ws, msg)

    async def send_hosts(self, obj):
        msg = json.dumps(obj)
        await asyncio.gather(*(safe_send(ws, msg) for ws in list(self.hosts)))

    async def broadcast(self):
        jobs = []
        for token, socks in list(self.sockets.items()):
            if token not in self.players:
                continue
            msg = json.dumps(self.player_state(token))
            jobs += [safe_send(ws, msg) for ws in list(socks)]
        await asyncio.gather(*jobs)
        await self.send_hosts(self.host_state())

    async def hard_reset(self):
        old = self.sockets
        self.reset()
        self.sockets = {}
        self.save()
        await asyncio.gather(*(safe_send(ws, {"t": "reset"}) for socks in old.values() for ws in socks))
        await self.send_hosts(self.host_state())


async def safe_send(ws, msg):
    try:
        if isinstance(msg, dict):
            msg = json.dumps(msg)
        await ws.send_str(msg)
    except Exception:  # noqa: BLE001 - a dropped phone must not break the broadcast
        pass


GAME = Game()


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
    await ws.prepare(request)
    token, is_host = None, False
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if token and token not in GAME.players:
                token = None  # kicked, or the host reset the game: this socket may join again
            t = data.get("t")
            if t == "hello":
                tok = data.get("token")
                if isinstance(tok, str) and data.get("game_id") == GAME.game_id and tok in GAME.players:
                    token = tok
                    GAME.sockets.setdefault(token, set()).add(ws)
                    await safe_send(ws, GAME.player_state(token))
                else:
                    await safe_send(ws, {"t": "need_join", "phase": GAME.phase, "open": is_open()})
            elif t == "join" and token is None:
                res = await GAME.join(ws, data.get("name"))
                if res["t"] == "joined":
                    token = res["token"]
                    await safe_send(ws, res)
                    await safe_send(ws, GAME.player_state(token))
                else:
                    res["open"] = is_open()
                    await safe_send(ws, res)
            elif t == "leave" and token:
                await GAME.leave(token)
                token = None
            elif t == "submit" and token:
                await GAME.submit(token, data)
            elif t == "host":
                pw = data.get("password")
                if isinstance(pw, str) and PASSWORD and hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                    is_host = True
                    GAME.hosts.add(ws)
                    await safe_send(ws, {"t": "host_ok"})
                    await safe_send(ws, GAME.host_state())
                else:
                    await asyncio.sleep(1)
                    await safe_send(ws, {"t": "host_denied"})
            elif t == "cmd" and is_host:
                cmd = data.get("cmd")
                log.info("host command: %s", cmd)
                if cmd == "start":
                    await GAME.start()
                elif cmd == "next":
                    await GAME.advance()
                elif cmd == "skip":
                    await GAME.skip()
                elif cmd == "winners":
                    await GAME.show_winners()
                elif cmd == "reset":
                    await GAME.hard_reset()
                elif cmd == "kick":
                    await GAME.kick(data.get("name", ""))
                elif cmd == "refresh":
                    await safe_send(ws, GAME.host_state())
    finally:
        if token and ws in GAME.sockets.get(token, ()):
            GAME.sockets[token].discard(ws)
        GAME.hosts.discard(ws)
    return ws


def page(name):
    async def handler(_request):
        return web.FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-cache"})

    return handler


_qr_cache = {}


async def qr(_request):
    if PUBLIC_URL not in _qr_cache:
        buf = io.BytesIO()
        segno.make(PUBLIC_URL, error="m").save(buf, kind="svg", scale=10, border=2, dark="#0d2731", light="#ffffff")
        _qr_cache[PUBLIC_URL] = buf.getvalue()
    return web.Response(body=_qr_cache[PUBLIC_URL], content_type="image/svg+xml")


async def healthz(_request):
    return web.Response(text="ok\n")


async def on_startup(_app):
    GAME.restore()


def make_app():
    app = web.Application()
    app.router.add_get("/", page("index.html"))
    app.router.add_get("/host", page("host.html"))
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/qr.svg", qr)
    app.router.add_get("/healthz", healthz)
    app.router.add_static("/static/", STATIC_DIR)
    app.on_startup.append(on_startup)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    if len(PASSWORD) < 8:
        raise SystemExit("ADMIN_PASSWORD must be set (8+ characters); see .env.example")
    load_config()  # fail fast on a broken questions file
    web.run_app(make_app(), host="0.0.0.0", port=8080, access_log=None)
