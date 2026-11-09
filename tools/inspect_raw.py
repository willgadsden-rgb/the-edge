"""Print the structure of the latest stored Form King card for a meeting (no API
credits: reads edge.raw_payloads). Usage: python tools/inspect_raw.py hamilton-20261109"""
import json, sys, zlib
sys.path.insert(0, ".")
from history_db import HistoryDB

ref = sys.argv[1] if len(sys.argv) > 1 else None
db = HistoryDB()
rows = db.query("SELECT endpoint, ref, pulled_at, body_zlib FROM raw_payloads WHERE ref LIKE ? ORDER BY pulled_at DESC LIMIT 3",
                ("%" + (ref or "") + "%",))
if len(sys.argv) > 2 and sys.argv[2] == "results":
    endpoint, r, pulled, body = rows[0]
    card = json.loads(zlib.decompress(bytes(body)))
    race = card["races"][0]
    print("officialTiming:", json.dumps(race.get("officialTiming"))[:400])
    for e in race["entries"]:
        print(e["horse"]["name"] if isinstance(e.get("horse"), dict) else e.get("horse"), "scr", e.get("scratched"), json.dumps(e.get("horseResult")))
    sys.exit(0)
for endpoint, r, pulled, body in rows:
    card = json.loads(zlib.decompress(bytes(body)))
    print("==", endpoint, r, pulled)
    print("card keys:", sorted(card.keys()))
    print("status:", card.get("status"))
    for race in (card.get("races") or [])[:2]:
        print(" race", race.get("raceId"), "status", race.get("status"), "keys:", sorted(race.keys()))
        for e in (race.get("entries") or [])[:2]:
            print("  entry keys:", sorted(e.keys()))
            pe = e.get("pastEvents") or []
            print("  pastEvents:", len(pe), "first raceId/date:", [(x.get("raceId"), x.get("date")) for x in pe[:2]])
            for k, v in e.items():
                if any(t in k.lower() for t in ("result", "finish", "position", "placing", "margin", "status", "dividend")):
                    print("   ", k, "=", json.dumps(v)[:200])
        for k, v in race.items():
            if any(t in k.lower() for t in ("result", "finish", "placing", "dividend", "status", "time")):
                print("  race", k, "=", json.dumps(v)[:300])
