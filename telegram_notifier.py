"""Telegram notifier for The Edge - Quantitative Racing Intelligence.

Formats syndicate value-alert cards for qualifying overlays and either sends
them to Telegram (when credentials are configured) or prints them to the console
in dry-run mode. Mock data only (see CLAUDE.md); no credentials are shipped, so
the default behaviour is a clean console dry-run.

Credentials are read from a local .env file (KEY=VALUE lines) or the process
environment: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"

CARD_WIDTH = 50


def _load_env():
    """Return a dict of config from .env (if present) overlaid by os.environ."""
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    # Process environment wins over the file.
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def format_alert_card(alert):
    """Render a single alert dict into the syndicate card string.

    Required alert keys: track_name, race_num, horse_name, barrier, weight,
    score_0_to_100, trend_str, prep_status, market_odds, fair_odds, edge_pct,
    mao, units, stake_cash.
    """
    bar = "=" * CARD_WIDTH
    rule = "-" * CARD_WIDTH
    return "\n".join([
        bar,
        "\U0001F6A8 THE EDGE VALUE ALERT | {track_name} R{race_num}".format(**alert),
        bar,
        "\U0001F3C7 Horse: {horse_name} (Barrier {barrier} | {weight}kg)".format(**alert),
        "\U0001F4CA Model Rating: {score_0_to_100} ({trend_str})".format(**alert),
        "\U0001F3AF Prep Stage: {prep_status}".format(**alert),
        rule,
        "\U0001F4B0 Market Price: ${market_odds:.2f}".format(**alert),
        "⚖️ Model Fair Price: ${fair_odds:.2f} (Edge: +{edge_pct:.1f}%)".format(**alert),
        "\U0001F6D1 Minimum Acceptable Odds (MAO): ${mao:.2f}".format(**alert),
        "\U0001F4B5 Recommended Stake: ${stake_dollars:,.2f} (to win ${to_win:.0f})".format(**alert),
        bar,
    ])


def _send_telegram(token, chat_id, text):
    """POST one message to the Telegram Bot API. Returns True on HTTP 200."""
    url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
        return resp.status == 200 and json.loads(body).get("ok", False)


def send_alerts(alerts):
    """Send (or dry-run print) all alert cards. Returns the mode used.

    Live sending only happens when BOTH TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
    are configured; otherwise every card is printed to the console.
    """
    env = _load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    live = bool(token and chat_id)

    if not alerts:
        print("No qualifying +EV overlays to alert (Edge >= 20% and Stake >= 0.5u).")
        return "none"

    mode = "live" if live else "dry-run"
    header = "Telegram: {} card(s) [{}]".format(len(alerts), mode.upper())
    print(header)
    print()

    for alert in alerts:
        card = format_alert_card(alert)
        if live:
            try:
                ok = _send_telegram(token, chat_id, card)
                status = "sent" if ok else "FAILED"
            except Exception as exc:  # pragma: no cover - network dependent
                status = "ERROR: {}".format(exc)
            print(card)
            print("  -> Telegram delivery: {}".format(status))
        else:
            print(card)
        print()

    if not live:
        print("(dry-run: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to send)")
    return mode


if __name__ == "__main__":
    demo = {
        "track_name": "Flemington", "race_num": 1,
        "horse_name": "Desert Mirage", "barrier": 2, "weight": 60.4,
        "score_0_to_100": 41.6, "trend_str": "DN -0.9/run",
        "prep_status": "[PEAK TARGET 3RD-UP]",
        "market_odds": 14.98, "fair_odds": 8.78, "edge_pct": 71.0,
        "mao": 10.10, "stake_dollars": 7.15, "to_win": 100,
    }
    send_alerts([demo])
