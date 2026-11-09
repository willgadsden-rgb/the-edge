"""Field check: pull ONE Form King meeting and save the raw JSON.

Standalone - needs nothing but Python 3 (no extra installs, no other files).
Run it from any folder:

    python3 field_check.py

It finds your Form King key in this order:
  1. environment variables FORMKING_API_KEY / FORMKING_BASE_URL
  2. .env.local, .env or .streamlit/secrets.toml in the current folder
  3. otherwise it asks you to paste the key (typing is hidden)

Costs 6 credits: 1 for the upcoming list + 5 for one meeting's full card.

Writes two files into the current folder:
    formking_sample.json   - the untouched API response for one meeting
    formking_fields.txt    - every field name found, with an example value

Send formking_sample.json back (it contains no API key).
"""

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.formking.com.au"
UPCOMING_PATH = "/b2c/meetings/upcoming"
SUMMARY_PATH = "/b2c/meetings/{meeting_id}"
OUT_DIR = Path.cwd()


def _from_files(name_pattern):
    """First value whose key matches name_pattern in the usual config files."""
    for fname in (".env.local", ".env", ".streamlit/secrets.toml"):
        path = OUT_DIR / fname
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            m = re.match(r'\s*([A-Za-z0-9_]+)\s*=\s*"?([^"#\n]+?)"?\s*(#.*)?$', line)
            if m and re.search(name_pattern, m.group(1), re.I):
                return m.group(2).strip()
    return None


def _config():
    key = (os.environ.get("FORMKING_API_KEY")
           or _from_files(r"FORM_?KING.*KEY"))
    if not key:
        key = getpass.getpass("Paste your Form King API key (hidden), then Enter: ").strip()
    if not key:
        sys.exit("No API key given.")
    base = (os.environ.get("FORMKING_BASE_URL")
            or _from_files(r"FORM_?KING.*(BASE|URL)")
            or DEFAULT_BASE_URL).rstrip("/")
    header = os.environ.get("FORMKING_AUTH_HEADER") or _from_files(r"FORM_?KING.*HEADER") or "x-api-key"
    return key, base, header


def _get(base, path, key, header):
    req = urllib.request.Request(base + path, headers={header: key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"Form King returned HTTP {e.code} for {path}. Check the key and base URL ({base}).")
    except urllib.error.URLError as e:
        sys.exit(f"Couldn't reach {base}: {e.reason}")


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
        for item in obj[:50]:
            _collect(item, prefix + "[]", found)


def main():
    key, base, header = _config()

    upcoming = _get(base, UPCOMING_PATH, key, header)
    if isinstance(upcoming, dict):
        upcoming = upcoming.get("meetings", [])
    if not upcoming:
        sys.exit("No upcoming meetings returned.")

    # Prefer a TAB meeting, soonest first.
    upcoming.sort(key=lambda m: (not m.get("tabMeeting", False), m.get("date") or 0))
    meeting = upcoming[0]
    print(f"Pulling {meeting.get('trackName')} (id {meeting.get('id')}) ...")

    summary = _get(base, SUMMARY_PATH.format(meeting_id=meeting["id"]), key, header)
    (OUT_DIR / "formking_sample.json").write_text(json.dumps(summary, indent=2))

    found = {}
    _collect(summary, "", found)
    lines = [f"{path} = {json.dumps(val)[:80]}" for path, val in sorted(found.items())]

    depths = [len(e.get("pastEvents") or [])
              for r in summary.get("races", []) for e in r.get("entries", [])]
    if depths:
        lines += ["", f"pastEvents per runner: min {min(depths)}, max {max(depths)}, "
                      f"avg {sum(depths) / len(depths):.1f} over {len(depths)} runners"]

    (OUT_DIR / "formking_fields.txt").write_text("\n".join(lines))
    print(f"Saved formking_sample.json and formking_fields.txt in {OUT_DIR} ({len(found)} fields).")


if __name__ == "__main__":
    main()
