"""Save this week's economic calendar (high and medium impact) to news.json for the website.

Source: the Forex Factory calendar feed - a free JSON feed with every event's exact time and time zone.
If the feed can't be reached, the previous news.json is kept, and the daily scores still run.
"""
import datetime
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "news.json")
URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def main():
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (Bias Desk daily calendar)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.load(r)
    except Exception as e:  # keep yesterday's file rather than writing nothing
        print("Calendar feed not reachable:", e)
        return 0
    events = []
    for e in data if isinstance(data, list) else []:
        imp = str(e.get("impact") or "").strip().lower()
        if imp not in ("high", "medium", "holiday"):
            continue
        try:
            t = datetime.datetime.fromisoformat(str(e.get("date")))
            if t.tzinfo is None:
                continue  # never guess a time zone
        except ValueError:
            continue
        events.append({
            "t": int(t.timestamp()),
            "cur": str(e.get("country") or "").upper(),
            "title": str(e.get("title") or "").strip(),
            "impact": imp,
            "forecast": str(e.get("forecast") or ""),
            "previous": str(e.get("previous") or ""),
        })
    if not events:
        print("Calendar feed returned no usable events - keeping the old file")
        return 0
    events.sort(key=lambda x: (x["t"], x["cur"]))
    out = {
        "source": "Forex Factory economic calendar",
        "fetched": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": events,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    high = sum(1 for e in events if e["impact"] == "high")
    print(f"Saved {len(events)} events ({high} high impact) to news.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
