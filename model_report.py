"""Print the form model's calibration and today's ratings from the history DB.

Run by .github/workflows/model-report.yml so the full Supabase history can be
checked without downloading it.
"""
import pandas as pd

from form_model import FormModel, load_history
from history_db import HistoryDB

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

db = HistoryDB()
h = load_history(db)
m = FormModel(h)
print("Runs: {:,}  horses: {:,}  races: {:,}".format(len(h), h["horse_name"].nunique(), h["race_id"].nunique()))
print("Runs with a rating: {:,}  with prep stage: {:,}".format(h["wfa_rating"].notna().sum(), h["stage"].notna().sum()))
print("\nLengths per rating point by distance:", {k: round(v, 3) for k, v in sorted(m.lpp_table.items())})
print("\nClass pars (median winning rating, races):")
for k, v in sorted(m.class_pars.items(), key=lambda kv: -kv[1]["races"])[:25]:
    print("  {:<12} {:5.1f}  ({} races)".format(k, v["par"], v["races"]))
print("\nPars by tier (top classes):")
for k, v in sorted(m.pars.items(), key=lambda kv: -kv[1]["races"])[:20]:
    print("  {:<12} {:<10} {:5.1f}  ({} races)".format(k[0], k[1], v["par"], v["races"]))
print("\nPrep stage, all horses:")
print(m.prep_population().to_string(index=False))

ent = db.query("SELECT e.horse_name, r.distance, r.going, r.restrictions, r.race_name, r.track, r.race_date, "
               "r.race_number, e.saddlecloth FROM entries e JOIN races r ON r.race_id = e.race_id "
               "WHERE r.race_date = (SELECT MAX(race_date) FROM races r2 JOIN entries e2 ON e2.race_id = r2.race_id) "
               "ORDER BY r.track, r.race_number, e.saddlecloth")
rows = []
for hn, dist, going, rest, rname, track, rdate, rno, cloth in ent:
    r = m.rate(hn, dist, going, rest or rname, track, rdate)
    rows.append({"Track": track, "R": rno, "No": cloth, "Horse": hn, "Class": r["class_group"],
                 "Ability": r["ability"], "Par": round(r["par"], 1) if r["par"] else None,
                 "Gap L": r["gap_l"], "Ceiling L": r["ceiling_gap_l"], "Conf": r["confidence"],
                 "Runs": r["runs_used"], "Best stage": m.best_stage(hn), "Badge": r["badge"]})
df = pd.DataFrame(rows)
print("\nToday's runners ({}):".format(len(df)))
print(df.head(40).to_string(index=False))
