"""Morning brief phone alert: today's strongest daily biases + today's high-impact news (times in SAST)."""
import json, os, sys, importlib.util as ilu
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sp = ilu.spec_from_file_location("bd_notify", os.path.join(HERE, "notify.py")); nm = ilu.module_from_spec(sp); sp.loader.exec_module(nm)
SAST = timezone(timedelta(hours=2))


def main():
    sc = json.load(open(os.path.join(ROOT, "scores.json")))
    today = datetime.now(SAST).strftime("%Y-%m-%d")
    if sc.get("date") != today:
        print("scores are not today's - no brief"); return 0
    items = sorted(sc["scores"].items(), key=lambda kv: -abs(kv[1]["score"]))
    lines = [f"{k} {v['score']:+d} {v['label']}" for k, v in items[:5]]
    news = []
    try:
        ev = json.load(open(os.path.join(ROOT, "news.json"))).get("events", [])
        for e in ev:
            t = datetime.fromtimestamp(e["t"], SAST)
            if e.get("impact") == "high" and t.strftime("%Y-%m-%d") == today:
                news.append(f"{t:%H:%M} {e['cur']} {e['title']}")
    except Exception as ex:
        print("news not read:", ex)
    msg = "Strongest biases:\n" + "\n".join(lines)
    msg += "\n\nHigh-impact news today (SAST):\n" + ("\n".join(news[:6]) if news else "none")
    nm.alert(f"Bias Desk morning brief {today}", msg, "default", ["sunrise"], nm.SITE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
