"""Dump the history tables to CSV for offline model work (run by the Export
workflow, which encrypts the files before uploading them)."""
import csv, sys
sys.path.insert(0, ".")
from history_db import HistoryDB

db = HistoryDB()
Q = {
    "runs": "SELECT x.*, r.race_date, r.track, r.state, r.distance, r.going AS race_going, r.restrictions, r.race_name, "
            "r.class_band, r.field_size AS race_field_size, r.race_number, r.rail, r.race_time_ms FROM runs x JOIN races r ON r.race_id = x.race_id",
    "horses": "SELECT * FROM horses",
    "entries": "SELECT e.*, r.race_date, r.track, r.state, r.distance, r.race_number FROM entries e JOIN races r ON r.race_id = e.race_id",
}
for name, sql in Q.items():
    cur = db.conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    with open("export_{}.csv".format(name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        n = 0
        for row in cur:
            w.writerow(row); n += 1
    print(name, n, "rows")
