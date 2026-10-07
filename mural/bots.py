"""Bot painters for testing Geeko Pixel Mural live. Bots join while the mural is open, paint a
pixel in their sector whenever their cooldown allows (usually the right colour), and join again
after the host presses Reset. Stop them with Ctrl-C.

    pip install aiohttp
    python mural/bots.py 100                  # 100 bots
    python mural/bots.py 50 --start 100       # a second batch with different names
    python mural/bots.py 100 --url http://localhost:8080/
"""
import argparse
import asyncio
import json
import random

import aiohttp

FIRST = ["Andi", "Budi", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hadi", "Intan", "Joko", "Kiki", "Lina",
         "Made", "Nina", "Oki", "Putri", "Rian", "Sari", "Tono", "Umi", "Vino", "Wati", "Yudi", "Zahra",
         "Akira", "Mei", "Linh", "Ravi", "Chen", "Yuki", "Arif", "Bayu", "Dimas", "Rina", "Tari", "Wahyu"]


def bot_name(i):
    return f"{FIRST[i]} bot" if i < len(FIRST) else f"{FIRST[i % len(FIRST)]} {i // len(FIRST) + 1}"


async def painter(ws, st, accuracy):
    """Paint while the phase is 'paint'; st is the shared state dict kept up to date by the reader."""
    while True:
        s = st.get("s")
        if not s or s["phase"] != "paint":
            await asyncio.sleep(0.5)
            continue
        cd = s["you"]["cooldown_ms"] / 1000
        await asyncio.sleep(cd + random.uniform(0.3, 2.5))  # people need a moment to pick
        s = st.get("s")
        if not s or s["phase"] != "paint":
            continue
        w, sw, sh = s["w"], s["sw"], s["sh"]
        sec = s["you"]["sector"]
        x0, y0 = (sec % (w // sw)) * sw, (sec // (w // sw)) * sh
        todo = [(y0 + r) * w + x0 + c for r in range(sh) for c in range(sw)
                if st["wall"][(y0 + r) * w + x0 + c] != s["target"][(y0 + r) * w + x0 + c]]
        if not todo:
            continue
        i = random.choice(todo)
        colour = s["target"][i] if random.random() < accuracy else random.choice(list(s["palette"]))
        await ws.send_str(json.dumps({"t": "paint", "i": i, "c": colour}))


async def bot(session, url, name, accuracy, stats):
    while True:
        joined, job = False, None
        try:
            async with session.ws_connect(url + "ws", heartbeat=20) as ws:
                st = {}
                job = asyncio.ensure_future(painter(ws, st, accuracy))
                await ws.send_str(json.dumps({"t": "join", "name": name}))
                async for m in ws:
                    d = json.loads(m.data)
                    t = d.get("t")
                    if t == "joined":
                        joined = True
                        stats["joined"] += 1
                    elif t == "state":
                        st["s"], st["wall"] = d, list(d["wall"])
                    elif t == "px" and "wall" in st:
                        for i, c in d["d"]:
                            st["wall"][i] = c
                    elif t == "painted":
                        stats["paints"] += 1
                    elif t in ("error", "need_join", "reset", "kicked", "left"):
                        if joined:
                            stats["joined"] -= 1
                        joined = False
                        st.clear()
                        if t == "kicked":
                            print(f"{name} was kicked, staying out", flush=True)
                            job.cancel()
                            return
                        await asyncio.sleep(3 + random.random() * 2)  # locked or finished: try again later
                        await ws.send_str(json.dumps({"t": "join", "name": name}))
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
            pass
        if job:
            job.cancel()
        if joined:
            stats["joined"] -= 1
        await asyncio.sleep(2)


async def main():
    ap = argparse.ArgumentParser(description="Bot painters for Geeko Pixel Mural")
    ap.add_argument("count", type=int, nargs="?", default=50)
    ap.add_argument("--url", default="https://quiz.opensuse.id/games/pixel-mural/")
    ap.add_argument("--accuracy", type=float, default=0.85, help="share of pixels painted in the right colour")
    ap.add_argument("--start", type=int, default=0, help="name offset, for a second batch")
    a = ap.parse_args()
    url = a.url if a.url.endswith("/") else a.url + "/"
    stats = {"joined": 0, "paints": 0}
    print(f"{a.count} bots -> {url} (waiting for the mural to be open)", flush=True)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        for i in range(a.start, a.start + a.count):
            asyncio.ensure_future(bot(session, url, bot_name(i), a.accuracy, stats))
            await asyncio.sleep(0.1)
        last = None
        while True:
            now = (stats["joined"], stats["paints"] // 100)
            if now != last:
                print(f"bots in game: {stats['joined']}/{a.count}, pixels painted: {stats['paints']}", flush=True)
                last = now
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
