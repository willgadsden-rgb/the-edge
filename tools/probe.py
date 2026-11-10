"""One-off probes (run by the Probe workflow):
1. Is Betfair's free daily file (with morning prices) reachable, and what's in it?
2. Can Form King return an old meeting card (results, opening flucs, form as of race day)?
Prints structure and counts only."""
import csv, io, json, sys
import requests
sys.path.insert(0, ".")

def betfair(day="08112026"):
    url = "https://promo.betfair.com/betfairsp/prices/dwbfpricesauswin{}.csv".format(day)
    try:
        r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        print("BETFAIR daily file:", r.status_code, len(r.content), "bytes")
        if r.ok:
            rows = list(csv.DictReader(io.StringIO(r.text)))
            print(" columns:", list(rows[0].keys()))
            print(" rows:", len(rows), "| with MORNINGWAP:", sum(1 for x in rows if (x.get("MORNINGWAP") or "").strip() not in ("", "0")),
                  "| with BSP:", sum(1 for x in rows if (x.get("BSP") or "").strip() not in ("", "0")))
            for x in rows[:3]:
                print(" ", {k: x[k] for k in list(x)[:17]})
            print(" menu hints:", sorted({x.get("MENU_HINT", "") for x in rows})[:12])
    except Exception as e:
        print("BETFAIR daily file failed:", repr(e)[:200])

def formking(ids):
    import formking_client as fk
    s = fk._session()
    for mid in ids:
        try:
            card = fk._get(s, fk._SUMMARY_PATH.format(meeting_id=mid))
        except Exception as e:
            print("FORMKING", mid, "failed:", repr(e)[:160]); continue
        races = card.get("races") or []
        print("FORMKING", mid, "status", card.get("status"), "races", len(races))
        if not races:
            continue
        r = races[0]; ents = r.get("entries") or []
        hr = [e.get("horseResult") for e in ents if e.get("horseResult")]
        print("  race1 entries", len(ents), "with result", len(hr), "| sample result keys:", sorted(hr[0].keys()) if hr else None)
        if hr:
            print("  sample flucs:", hr[0].get("officialFlucs"), "sp", hr[0].get("startingPrice"), "bsp", hr[0].get("betfairStartingPrice"))
        e = next((x for x in ents if x.get("pastEvents")), None)
        if e:
            pe = e["pastEvents"]
            print("  race date ms:", r.get("date"), "| first runner's newest past run date ms:", pe[0].get("date"), "raceId", pe[0].get("raceId"),
                  "| past runs:", len(pe), "| is this race in its own past runs:", any(x.get("raceId") == r.get("raceId") for x in pe))
            print("  odds:", json.dumps(e.get("odds"))[:200], "| ratings:", json.dumps(e.get("ratings"))[:160])
            print("  past run rated?", pe[0].get("weightForAgeRating"), "| trials:", len(e.get("recentTrials") or []))

if __name__ == "__main__":
    betfair()
    formking(sys.argv[1:])
