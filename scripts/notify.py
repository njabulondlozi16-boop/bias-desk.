"""Phone alerts for Bias Desk (ntfy, free, no account; optional Telegram).

Set the repo secret NTFY_TOPIC to your private topic name and subscribe to that topic in the ntfy app.
Without the secret this script does nothing (and says so), so jobs never fail because of alerts.

Usage (command line):  python scripts/notify.py --title "..." --message "..." [--priority high] [--tags chart] [--click URL]
Usage (from Python):   from notify import alert; alert("Title", "Message", priority="default")
"""
import argparse, json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

SAST = timezone(timedelta(hours=2))
SITE = "https://njabulondlozi16-boop.github.io/bias-desk./"
PRIORITY = {"min": 1, "low": 2, "default": 3, "normal": 3, "high": 4, "urgent": 5}


def _quiet_now():
    h = datetime.now(SAST).hour
    return h >= 22 or h < 5


def _post(url, data, headers, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except Exception as e:  # network hiccup: back off and retry
            err = e
            time.sleep(2 * (i + 1))
    print(f"alert not sent: {err}", file=sys.stderr)
    return None


def alert(title, message, priority="default", tags=None, click=None):
    """Send one alert. Quiet hours (22:00-05:00 SAST) only let 'high'/'urgent' through."""
    pr = PRIORITY.get(str(priority).lower(), 3)
    if _quiet_now() and pr < 4:
        print(f"quiet hours - alert held back: {title}")
        return False
    sent = False
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Priority": str(pr),
                   "Click": click or SITE}
        if tags:
            headers["Tags"] = ",".join(tags) if isinstance(tags, (list, tuple)) else str(tags)
        # ntfy accepts UTF-8 bodies; titles must be header-safe, so emoji go in the body/tags
        st = _post(f"https://ntfy.sh/{urllib.parse.quote(topic)}", message.encode("utf-8"), headers)
        sent = sent or (st is not None and st < 300)
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if tok and chat:
        body = json.dumps({"chat_id": chat, "text": f"{title}\n{message}\n{click or SITE}", "disable_web_page_preview": True}).encode()
        st = _post(f"https://api.telegram.org/bot{tok}/sendMessage", body, {"Content-Type": "application/json"})
        sent = sent or (st is not None and st < 300)
    if not topic and not (tok and chat):
        print("alerts are off: add the NTFY_TOPIC secret to turn them on")
    elif sent:
        print(f"alert sent: {title}")
    return sent


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--priority", default="default")
    ap.add_argument("--tags", default="")
    ap.add_argument("--click", default=None)
    a = ap.parse_args()
    alert(a.title, a.message, a.priority, [t for t in a.tags.split(",") if t], a.click)
