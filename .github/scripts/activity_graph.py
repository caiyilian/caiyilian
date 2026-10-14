#!/usr/bin/env python3
"""Generate self-hosted contribution activity graph SVGs (dark/light) for the profile README.

No arguments:  python3 activity_graph.py
Requires: `gh` CLI authenticated via the GH_TOKEN environment variable
(works both locally and inside GitHub Actions with ${{ github.token }}).
Writes: dist/activity-graph-dark.svg, dist/activity-graph-light.svg
Data:   last 31 days of contributions via GraphQL, with a public-events fallback.
"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

USER = "caiyilian"
DAYS = 31
OUT_DIR = "dist"


def gh(*args):
    r = subprocess.run(["gh", "api"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("gh api %s failed: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:400]))
    return r.stdout


def fetch_contributions():
    """Return {date: count} from the contribution calendar (last ~1 year of days)."""
    query = ('query { user(login: "%s") { contributionsCollection { contributionCalendar '
             '{ weeks { contributionDays { date contributionCount } } } } } }' % USER)
    data = json.loads(gh("graphql", "-f", "query=" + query))
    out = {}
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            out[day["date"]] = day["contributionCount"]
    return out


def fetch_events_fallback():
    """Fallback: aggregate public PushEvents into daily commit counts."""
    out = {}
    for page in range(1, 4):
        events = json.loads(gh("/users/%s/events/public?per_page=100&page=%d" % (USER, page)))
        if not events:
            break
        for ev in events:
            if ev.get("type") == "PushEvent":
                day = ev["created_at"][:10]
                out[day] = out.get(day, 0) + len(ev.get("payload", {}).get("commits", []))
    return out


def series():
    try:
        data = fetch_contributions()
    except Exception as exc:  # noqa: BLE001
        print("GraphQL failed (%s); falling back to public events API" % exc)
        data = fetch_events_fallback()
    today = date.today()
    return [(today - timedelta(days=i),
             data.get((today - timedelta(days=i)).isoformat(), 0))
            for i in range(DAYS - 1, -1, -1)]


THEMES = {
    "dark": dict(accent="#58a6ff", muted="#8b949e", grid="#21262d", grad="agDark"),
    "light": dict(accent="#0969da", muted="#57606a", grid="#d8dee4", grad="agLight"),
}


def smooth(points):
    if len(points) < 2:
        return ""
    d = "M %.2f %.2f" % points[0]
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0
        c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0
        d += " C %.2f %.2f %.2f %.2f %.2f %.2f" % (c1x, c1y, c2x, c2y, p2[0], p2[1])
    return d


def build(days, theme):
    t = THEMES[theme]
    W, H = 820, 200
    left, right, top, bottom = 28, 22, 48, 30
    pw, ph = W - left - right, H - top - bottom
    values = [v for _, v in days]
    vmax = max(max(values), 4)
    n = len(days)
    step = pw / float(n - 1)
    pts = [(left + i * step, top + ph - (v / float(vmax)) * ph) for i, (_, v) in enumerate(days)]
    line = smooth(pts)
    area = line + " L %.2f %.2f L %.2f %.2f Z" % (pts[-1][0], top + ph, pts[0][0], top + ph)
    total = sum(values)
    d0, d1 = days[0][0], days[-1][0]
    fmt = lambda dd: "%d/%d" % (dd.month, dd.day)

    p = []
    p.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
             'font-family="-apple-system,\'Segoe UI\',Helvetica,Arial,sans-serif">' % (W, H, W, H))
    p.append('<defs><linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0%%" stop-color="%s" stop-opacity="0.30"/>'
             '<stop offset="100%%" stop-color="%s" stop-opacity="0.02"/>'
             '</linearGradient></defs>' % (t["grad"], t["accent"], t["accent"]))
    for k in range(5):
        y = top + ph - ph * k / 4.0
        dash = ' stroke-dasharray="3,5"' if 0 < k < 4 else ""
        p.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="1"%s/>'
                 % (left, y, W - right, y, t["grid"], dash))
        if k in (0, 4):
            p.append('<text x="%.2f" y="%.2f" font-size="10" fill="%s" text-anchor="end">%d</text>'
                     % (left - 6, y + 3.5, t["muted"], int(round(vmax * k / 4.0))))
    for i in (0, 6, 12, 18, 24, 30):
        if i < n:
            p.append('<text x="%.2f" y="%.2f" font-size="9.5" fill="%s" text-anchor="middle">%s</text>'
                     % (left + i * step, H - 12, t["muted"], fmt(days[i][0])))
    p.append('<text x="%d" y="27" font-size="15" font-weight="600" fill="%s">Contribution Graph</text>'
             % (left, t["accent"]))
    p.append('<text x="%d" y="27" font-size="11" fill="%s" text-anchor="end">Total %d · %s – %s</text>'
             % (W - right, t["muted"], total, fmt(d0), fmt(d1)))
    p.append('<path d="%s" fill="url(#%s)"/>' % (area, t["grad"]))
    p.append('<path d="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round" '
             'stroke-linecap="round"/>' % (line, t["accent"]))
    for (x, y), (_, v) in zip(pts, days):
        if v > 0:
            p.append('<circle cx="%.2f" cy="%.2f" r="2.1" fill="%s"/>' % (x, y, t["accent"]))
    p.append("</svg>")
    return "".join(p)


def main():
    days = series()
    os.makedirs(OUT_DIR, exist_ok=True)
    for theme in ("dark", "light"):
        svg = build(days, theme)
        path = os.path.join(OUT_DIR, "activity-graph-%s.svg" % theme)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print("wrote %s (%d bytes)" % (path, len(svg)))
    print("total contributions in range: %d" % sum(v for _, v in days))


if __name__ == "__main__":
    main()
