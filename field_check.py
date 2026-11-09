"""Field check: pull ONE Form King meeting and save the raw JSON.

Run this once on your own machine (it uses the same key setup as the app:
.streamlit/secrets.toml or environment variables). It costs 6 credits:
1 for the upcoming list + 5 for one meeting's full card.

    python field_check.py

Writes two files next to this script:
    formking_sample.json   - the untouched API response for one meeting
    formking_fields.txt    - every field name found, by level, with an example value

Send formking_sample.json back (it contains no API key).
"""

import json
from pathlib import Path

import formking_client as fk

OUT_DIR = Path(__file__).resolve().parent


def _collect(obj, prefix, found):
    """Record every key path in obj with one example value."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                _collect(v, path, found)
            elif path not in found:
                found[path] = v
    elif isinstance(obj, list):
        for item in obj[:50]:          # enough items to see every key
            _collect(item, prefix + "[]", found)


def main():
    session = fk._session()
    upcoming = fk._get(session, fk._UPCOMING_PATH)
    if isinstance(upcoming, dict):
        upcoming = upcoming.get("meetings", [])
    if not upcoming:
        raise SystemExit("No upcoming meetings returned.")

    # Prefer a TAB meeting, soonest first.
    upcoming.sort(key=lambda m: (not m.get("tabMeeting", False), m.get("date") or 0))
    meeting = upcoming[0]
    print(f"Pulling {meeting.get('trackName')} (id {meeting.get('id')}) ...")

    summary = fk._get(session, fk._SUMMARY_PATH.format(meeting_id=meeting["id"]))
    (OUT_DIR / "formking_sample.json").write_text(json.dumps(summary, indent=2))

    found = {}
    _collect(summary, "", found)
    lines = [f"{path} = {json.dumps(val)[:80]}" for path, val in sorted(found.items())]

    # How deep does pastEvents go?
    depths = [len(e.get("pastEvents") or [])
              for r in summary.get("races", []) for e in r.get("entries", [])]
    if depths:
        lines.append("")
        lines.append(f"pastEvents per runner: min {min(depths)}, max {max(depths)}, "
                     f"avg {sum(depths) / len(depths):.1f} over {len(depths)} runners")

    (OUT_DIR / "formking_fields.txt").write_text("\n".join(lines))
    print(f"Saved formking_sample.json and formking_fields.txt ({len(found)} fields).")


if __name__ == "__main__":
    main()
