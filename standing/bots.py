"""Bot players for testing Last Geeko Standing live. Bots join while the game is open, answer every
question and send believable mini game scores, and join again after the host presses Reset.
Stop them with Ctrl-C.

    pip install aiohttp
    python standing/bots.py 200                 # 200 bots at normal skill
    python standing/bots.py 200 --skill weak    # bots that lose, so you reach the final yourself
    python standing/bots.py 50 --start 200      # a second batch with different names

Bots do not really play the mini games: they wait part of the game time and send a score.
"""
import argparse
import asyncio
import json
import os
import random

import aiohttp

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = {"weak": (0.1, 0.35), "normal": (0.55, 0.95), "strong": (0.85, 1.0)}
FIRST = ["Andi", "Budi", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hadi", "Intan", "Joko", "Kiki", "Lina",
         "Made", "Nina", "Oki", "Putri", "Rian", "Sari", "Tono", "Umi", "Vino", "Wati", "Yudi", "Zahra",
         "Akira", "Mei", "Linh", "Ravi", "Chen", "Yuki", "Arif", "Bayu", "Dimas", "Rina", "Tari", "Wahyu"]
GAME_SECONDS = {"color": 20, "reflex": 18, "odd": 22, "sort": 22, "bug": 22, "simon": 26, "dash": 20}


def bot_name(i):
    return f"{FIRST[i]} bot" if i < len(FIRST) else f"{FIRST[i % len(FIRST)]} {i // len(FIRST) + 1}"


async def answer(ws, d, skill, cfg):
    r, i = d["round"]["index"], d["round"]["item"]
    it, base = d["item"], {"t": "submit", "round": r, "item": i}
    s = random.uniform(*skill)
    if it["kind"] == "question":
        await asyncio.sleep(random.uniform(1, 6))
        truth = cfg["rounds"][r]["questions"][i]["answer"]
        msg = dict(base, choice=truth if random.random() < s else not truth, ms=random.randint(1000, 6000))
    else:
        g = it["game"]
        secs = GAME_SECONDS.get(g, 15)
        await asyncio.sleep(random.uniform(secs * 0.6, secs * 0.9))  # "play" for a while
        if g in ("color", "dash"):
            msg = dict(base, correct=int(random.randint(6, 18) * s), wrong=random.randint(0, 4))
        elif g == "reflex":
            msg = dict(base, hits=int(random.randint(6, 15) * s), wrong=random.randint(0, 3),
                       avg=int(random.randint(330, 700) / max(s, 0.5)))
        elif g == "sort":
            msg = dict(base, sorted=int(random.randint(8, 30) * s), wrong=random.randint(0, 3),
                       ms=random.randint(10000, 24000))
        elif g == "bug":
            msg = dict(base, hits=int(random.randint(8, 30) * s), misses=random.randint(0, 3))
        elif g == "simon":
            msg = dict(base, level=int(random.randint(1, 8) * s), ms=random.randint(8000, 26000))
        else:
            msg = dict(base, levels=int(random.randint(2, 9) * s), ms=random.randint(8000, 22000))
    await ws.send_str(json.dumps(msg))


async def bot(session, url, name, skill, cfg, stats):
    joined = False
    while True:
        try:
            async with session.ws_connect(url + "ws", heartbeat=20) as ws:
                joined, done = False, set()
                await ws.send_str(json.dumps({"t": "join", "name": name}))
                async for m in ws:
                    d = json.loads(m.data)
                    t = d.get("t")
                    if t == "joined":
                        joined = True
                        stats["joined"] += 1
                    elif t in ("error", "need_join", "reset", "kicked"):
                        if joined:
                            stats["joined"] -= 1
                        joined, done = False, set()
                        if t == "kicked":
                            print(f"{name} was kicked, staying out", flush=True)
                            return
                        await asyncio.sleep(3 + random.random() * 2)  # locked or started: try again later
                        await ws.send_str(json.dumps({"t": "join", "name": name}))
                    elif t == "state" and d.get("phase") == "play" and not d["you"]["out"] and not d["you"]["done"]:
                        key = (d["round"]["index"], d["round"]["item"])
                        if key not in done:
                            done.add(key)
                            asyncio.ensure_future(answer(ws, d, skill, cfg))
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
            pass
        if joined:
            stats["joined"] -= 1
            joined = False
        await asyncio.sleep(2)


async def main():
    ap = argparse.ArgumentParser(description="Bot players for Last Geeko Standing")
    ap.add_argument("count", type=int, nargs="?", default=30)
    ap.add_argument("--url", default="https://quiz.opensuse.id/games/last-geeko-standing/")
    ap.add_argument("--skill", choices=SKILLS, default="normal")
    ap.add_argument("--start", type=int, default=0, help="name offset, for a second batch")
    ap.add_argument("--questions", default=os.path.join(HERE, "..", "config", "last-geeko-standing-questions.json"))
    a = ap.parse_args()
    url = a.url if a.url.endswith("/") else a.url + "/"
    cfg = json.load(open(a.questions))
    stats = {"joined": 0}
    print(f"{a.count} {a.skill} bots -> {url} (waiting for the game to be open and in the lobby)", flush=True)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as session:
        for i in range(a.start, a.start + a.count):
            asyncio.ensure_future(bot(session, url, bot_name(i), SKILLS[a.skill], cfg, stats))
            await asyncio.sleep(0.15)  # trickle in like a real audience
        last = None
        while True:
            if stats["joined"] != last:
                print(f"bots in game: {stats['joined']}/{a.count}", flush=True)
                last = stats["joined"]
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
