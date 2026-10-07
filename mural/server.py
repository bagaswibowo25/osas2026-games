"""Geeko Pixel Mural: everyone paints one big pixel mural together from their phone.

The wall is 96 x 54 pixels and shows a faint pattern (OPENSUSE.ASIA / SUMMIT 2026 / YOGYAKARTA on
a kawung batik background). Every player gets a sector of 12 x 9 pixels and paints one pixel at
a time (with a short cooldown) in the colour the pattern asks for. The projector shows the wall
filling up live. When the time is up the rest is filled in and the finished mural is revealed.

One process holds the wall in memory and snapshots it to /data, so a restart resumes.

  GET /            player page
  GET /host        host page: projector view + controls (ADMIN_PASSWORD)
  GET /qr.svg      QR code of the player URL
  GET /ws          WebSocket

Players can only join while the game is open: /games/admin writes {"open": true|false} to
config/pixel-mural.json. Optional config/pixel-mural-settings.json: {"seconds": 180, "cooldown": 3}.
"""

import asyncio
import hmac
import io
import json
import logging
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
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://quiz.opensuse.id/games/pixel-mural/")
LOCK_FILE = CONFIG_DIR / "pixel-mural.json"
SETTINGS_FILE = CONFIG_DIR / "pixel-mural-settings.json"
STATE_FILE = DATA_DIR / "pixel-mural.json"

W, H = 96, 54  # the wall, 16:9
SW, SH = 12, 9  # one sector: 8 x 6 sectors, named A1..F8
SCOLS, SROWS = W // SW, H // SH
MAX_NAME = 20
COUNTDOWN = 4.5
FLUSH = 0.2  # seconds between batched pixel updates

PALETTE = {"p": "#173f4f", "d": "#0b2a35", "g": "#73ba25", "j": "#35b9ab", "b": "#21a4df",
           "k": "#c9a24a", "w": "#ffffff"}
NAMES = {"p": "Pine", "d": "Night", "g": "Green", "j": "Teal", "b": "Blue", "k": "Batik gold", "w": "White"}

log = logging.getLogger("mural")

# ----- the pattern -------------------------------------------------------------------------------
FONT = {  # 5 x 7
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "E": "11111 10000 10000 11110 10000 10000 11111", "N": "10001 11001 10101 10011 10001 10001 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "U": "10001 10001 10001 10001 10001 10001 01110",
    ".": "00000 00000 00000 00000 00000 01100 01100", "A": "01110 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "M": "10001 11011 10101 10101 10001 10001 10001",
    "T": "11111 00100 00100 00100 00100 00100 00100", "2": "01110 10001 00001 00010 00100 01000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "6": "00110 01000 10000 11110 10001 10001 01110",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "G": "01110 10001 10000 10111 10001 10001 01111",
    "K": "10001 10010 10100 11000 10100 10010 10001", "R": "11110 10001 10001 11110 10100 10010 10001",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}
# Kawung batik tile: gold petals around a teal centre
KAWUNG = ["...gg...", "..gggg..", "g..gg..g", "gg.ww.gg", "gg.ww.gg", "g..gg..g", "..gggg..", "...gg..."]


def build_target():
    import math
    t = [["p"] * W for _ in range(H)]
    for r in range(H):
        for c in range(W):
            wave = 2 + 1.6 * math.sin(c / 3.6)
            if r < 5:
                t[r][c] = "b" if r < wave else "j"
            elif r >= H - 5:
                t[r][c] = "b" if (H - 1 - r) < wave else "j"
            else:
                ch = KAWUNG[(r - 5) % 8][c % 8]
                t[r][c] = "k" if ch == "g" else "j" if ch == "w" else "p"
    # Dark panel with a teal frame for the text
    for r in range(9, 45):
        for c in range(5, 91):
            t[r][c] = "j" if r in (9, 44) or c in (5, 90) else "d"

    def write(text, top, colour):
        left = (W - (len(text) * 6 - 1)) // 2
        for i, ch in enumerate(text):
            rows = FONT[ch].split()
            for r in range(7):
                for c in range(5):
                    if rows[r][c] == "1":
                        t[top + r][left + i * 6 + c] = colour

    write("OPENSUSE.ASIA", 12, "g")
    write("SUMMIT 2026", 23, "w")
    write("YOGYAKARTA", 34, "k")
    return "".join("".join(row) for row in t)


TARGET = build_target()


def sector_of(i):
    r, c = divmod(i, W)
    return (r // SH) * SCOLS + c // SW


def sector_name(s):
    return "ABCDEF"[s // SCOLS] + str(s % SCOLS + 1)


SECTOR_PIXELS = [[] for _ in range(SCOLS * SROWS)]
for _i in range(W * H):
    SECTOR_PIXELS[sector_of(_i)].append(_i)


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    seconds = data.get("seconds", 180)
    cooldown = data.get("cooldown", 3)
    return {"seconds": int(seconds) if isinstance(seconds, (int, float)) and 30 <= seconds <= 1800 else 180,
            "cooldown": float(cooldown) if isinstance(cooldown, (int, float)) and 0.5 <= cooldown <= 30 else 3.0}


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


class Mural:
    def __init__(self):
        self.sockets = {}  # token -> set of player WebSockets
        self.hosts = set()
        self.timer = None
        self.pending = []  # [index, colour] not yet sent
        self.feed = []  # last paints for the projector
        self._save_pending = False
        self.flusher = None
        self.reset()

    # ----- state -------------------------------------------------------------
    def reset(self):
        self.cancel_timer()
        self.game_id = secrets.token_hex(6)
        self.phase = "lobby"  # lobby countdown paint done
        self.settings = load_settings()
        self.wall = ["."] * (W * H)  # "." = not painted yet
        self.players = {}  # token -> {name, sector, painted, matched, last}
        self.names = {}
        self.deadline = 0.0
        self.next_action = ""
        self.pending = []
        self.feed = []

    def snapshot(self):
        return {"game_id": self.game_id, "phase": self.phase, "settings": self.settings, "wall": "".join(self.wall),
                "players": self.players, "deadline": self.deadline, "next_action": self.next_action}

    def save(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".mural.", suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(self.snapshot(), f)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log.warning("cannot save state: %s", e)

    def save_soon(self):
        if self._save_pending:
            return
        self._save_pending = True

        def run():
            self._save_pending = False
            self.save()

        asyncio.get_running_loop().call_later(1.0, run)

    def restore(self):
        try:
            data = json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            return
        if len(data.get("wall", "")) != W * H:
            return
        self.game_id, self.phase, self.settings = data["game_id"], data["phase"], data["settings"]
        self.wall = list(data["wall"])
        self.players = data["players"]
        self.names = {p["name"].lower(): t for t, p in self.players.items()}
        self.deadline, self.next_action = data["deadline"], data["next_action"]
        log.info("restored mural %s: phase %s, %d players, %d%% done", self.game_id, self.phase,
                 len(self.players), self.percent())
        if self.next_action:
            self.schedule(max(0.5, self.deadline - time.time()), getattr(self, self.next_action))

    # ----- helpers -----------------------------------------------------------
    def schedule(self, delay, fn):
        self.cancel_timer()
        self.next_action = fn.__name__
        self.timer = asyncio.get_running_loop().call_later(delay, lambda: asyncio.ensure_future(fn()))

    def cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.next_action = ""

    def matched(self):
        return sum(1 for i, c in enumerate(self.wall) if c == TARGET[i])

    def percent(self):
        return round(100 * self.matched() / (W * H))

    def sector_left(self, s):
        return sum(1 for i in SECTOR_PIXELS[s] if self.wall[i] != TARGET[i])

    def pick_sector(self, avoid=None):
        """The sector with the most pixels left per painter in it."""
        count = [0] * (SCOLS * SROWS)
        for p in self.players.values():
            count[p["sector"]] += 1
        best, best_score = 0, -1.0
        for s in range(SCOLS * SROWS):
            if s == avoid:
                continue
            left = self.sector_left(s)
            score = left / (count[s] + 1) if left else -0.5 / (count[s] + 1)
            if score > best_score:
                best, best_score = s, score
        return best

    # ----- flow --------------------------------------------------------------
    async def start(self):
        if self.phase != "lobby":
            return
        self.settings = load_settings()
        self.phase = "countdown"
        self.deadline = time.time() + COUNTDOWN
        self.schedule(COUNTDOWN, self.begin_paint)
        self.save()
        await self.broadcast()

    async def begin_paint(self):
        if self.phase != "countdown":
            return
        self.phase = "paint"
        self.deadline = time.time() + self.settings["seconds"]
        self.schedule(self.settings["seconds"], self.finish)
        self.save()
        await self.broadcast()

    async def finish(self):
        if self.phase not in ("paint", "countdown"):
            return
        self.cancel_timer()
        await self.flush()
        self.phase = "done"
        self.save()
        await self.broadcast()

    # ----- players -----------------------------------------------------------
    async def join(self, ws, raw_name):
        if self.phase == "done":
            return {"t": "error", "code": "done"}
        if not is_open():
            return {"t": "error", "code": "locked"}
        name = clean_name(raw_name)
        if not name:
            return {"t": "error", "code": "bad_name"}
        if name.lower() in self.names:
            return {"t": "error", "code": "name_taken"}
        token = secrets.token_urlsafe(16)
        self.players[token] = {"name": name, "sector": self.pick_sector(), "painted": 0, "matched": 0, "last": 0.0}
        self.names[name.lower()] = token
        self.sockets.setdefault(token, set()).add(ws)
        self.save_soon()
        await self.send_hosts(self.host_stats())
        return {"t": "joined", "token": token, "game_id": self.game_id, "name": name}

    async def leave(self, token):
        p = self.players.pop(token, None)
        if not p:
            return
        self.names.pop(p["name"].lower(), None)
        for ws in self.sockets.pop(token, set()):
            await safe_send(ws, {"t": "left"})
        self.save_soon()
        await self.send_hosts(self.host_stats())

    async def kick(self, name):
        token = self.names.get(str(name).lower())
        if not token:
            return
        p = self.players.pop(token)
        self.names.pop(p["name"].lower(), None)
        for ws in self.sockets.pop(token, set()):
            await safe_send(ws, {"t": "kicked"})
        self.save_soon()
        await self.send_hosts(self.host_stats())

    async def paint(self, token, data):
        p = self.players.get(token)
        i, colour = data.get("i"), data.get("c")
        if self.phase != "paint" or not p:
            return
        if not (isinstance(i, int) and not isinstance(i, bool) and 0 <= i < W * H) or colour not in PALETTE:
            return
        now = time.time()
        if now - p["last"] < self.settings["cooldown"] - 0.25 or sector_of(i) != p["sector"]:
            return
        if self.wall[i] == TARGET[i]:
            return  # already right: nobody can paint over a finished pixel
        p["last"] = now
        p["painted"] += 1
        self.wall[i] = colour
        ok = colour == TARGET[i]
        if ok:
            p["matched"] += 1
        self.pending.append([i, colour])
        self.feed = (self.feed + [{"who": p["name"], "sector": sector_name(p["sector"]), "c": colour, "ok": ok}])[-6:]
        self.save_soon()
        await self.send_player(token, {"t": "painted", "i": i, "c": colour, "ok": ok, "painted": p["painted"],
                                       "matched": p["matched"], "cooldown_ms": int(self.settings["cooldown"] * 1000)})
        if ok and self.sector_left(p["sector"]) == 0:
            await self.sector_done(p["sector"])

    async def sector_done(self, s):
        """Everyone in a finished sector moves on to the one that needs help most."""
        for t, p in self.players.items():
            if p["sector"] == s:
                p["sector"] = self.pick_sector(avoid=s)
                await self.send_player(t, dict(self.player_state(t), moved=sector_name(s)))

    async def flush_loop(self):
        while True:
            await asyncio.sleep(FLUSH)
            try:
                await self.flush()
            except Exception:  # noqa: BLE001 - keep the loop alive whatever happens
                log.exception("flush failed")

    async def flush(self):
        if not self.pending:
            return
        diff, self.pending = self.pending, []
        pct = self.percent()
        msg = json.dumps({"t": "px", "d": diff, "pct": pct})
        jobs = [safe_send(ws, msg) for token, socks in self.sockets.items() if token in self.players for ws in socks]
        await asyncio.gather(*jobs)
        await self.send_hosts({"t": "px", "d": diff, "pct": pct, "feed": self.feed,
                               "painters": sum(1 for p in self.players.values() if p["painted"])})

    # ----- what each screen gets ----------------------------------------------
    def common(self, s):
        s.update({"game_id": self.game_id, "phase": self.phase, "w": W, "h": H, "sw": SW, "sh": SH,
                  "palette": PALETTE, "names": NAMES, "pct": self.percent(), "players": len(self.players)})
        if self.phase in ("countdown", "paint"):
            s["ends_in_ms"] = max(0, int((self.deadline - time.time()) * 1000))
            s["total_ms"] = int((COUNTDOWN if self.phase == "countdown" else self.settings["seconds"]) * 1000)
        return s

    def player_state(self, token):
        p = self.players[token]
        s = self.common({"t": "state", "target": TARGET, "wall": "".join(self.wall)})
        wait = max(0.0, p["last"] + self.settings["cooldown"] - time.time())
        s["you"] = {"name": p["name"], "sector": p["sector"], "sector_name": sector_name(p["sector"]),
                    "painted": p["painted"], "matched": p["matched"], "wait_ms": int(wait * 1000),
                    "cooldown_ms": int(self.settings["cooldown"] * 1000)}
        if self.phase == "done":
            s["you"]["rank"] = self.rank_of(token)
        return s

    def ranking(self):
        return sorted(self.players.items(), key=lambda kv: (-kv[1]["matched"], kv[1]["painted"]))

    def rank_of(self, token):
        for k, (t, _) in enumerate(self.ranking(), 1):
            if t == token:
                return k
        return 0

    def host_stats(self):
        return {"t": "stats", "players": len(self.players), "open": is_open(),
                "who": [p["name"] for p in self.players.values()][-60:]}

    def host_state(self):
        s = self.common({"t": "host_state", "target": TARGET, "wall": "".join(self.wall), "open": is_open(),
                         "url": PUBLIC_URL, "feed": self.feed,
                         "painters": sum(1 for p in self.players.values() if p["painted"]),
                         "who": [p["name"] for p in self.players.values()][-60:],
                         "settings": self.settings})
        if self.phase == "done":
            s["top"] = [{"name": p["name"], "matched": p["matched"]} for _, p in self.ranking()[:8] if p["matched"]]
            s["paints"] = sum(p["painted"] for p in self.players.values())
        return s

    # ----- sending -----------------------------------------------------------
    async def send_player(self, token, obj):
        msg = json.dumps(obj)
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


GAME = Mural()


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
                token = None  # kicked, left or reset: this socket may join again
            t = data.get("t")
            if t == "paint" and token:
                await GAME.paint(token, data)
            elif t == "hello":
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
                elif cmd == "finish":
                    await GAME.finish()
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
    GAME.flusher = asyncio.ensure_future(GAME.flush_loop())


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
    web.run_app(make_app(), host="0.0.0.0", port=8080, access_log=None)
