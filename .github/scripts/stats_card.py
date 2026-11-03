#!/usr/bin/env python3
"""Generate self-hosted GitHub stats card SVGs (dark/light) for the profile README.

No arguments:  python3 stats_card.py
Requires: `gh` CLI authenticated via the GH_TOKEN environment variable
(works both locally and inside GitHub Actions with ${{ github.token }}).
Writes: dist/github-stats-dark.svg, dist/github-stats-light.svg

All displayed numbers and the rank letter are fetched/computed at run time.
The rank uses the same formula as the upstream github-readme-stats project
(exponential CDF for counts, log-normal CDF for stars/followers, weighted sum),
so the letter matches what the public card would show.
"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

USER = "caiyilian"
OUT_DIR = "dist"

# --- rank model (ported from anuraghazra/github-readme-stats calculateRank.js) ---
COMMITS_MEDIAN, COMMITS_WEIGHT = 250, 2
PRS_MEDIAN, PRS_WEIGHT = 50, 3
ISSUES_MEDIAN, ISSUES_WEIGHT = 25, 1
REVIEWS_MEDIAN, REVIEWS_WEIGHT = 2, 1
STARS_MEDIAN, STARS_WEIGHT = 50, 4
FOLLOWERS_MEDIAN, FOLLOWERS_WEIGHT = 10, 1
TOTAL_WEIGHT = (COMMITS_WEIGHT + PRS_WEIGHT + ISSUES_WEIGHT
                + REVIEWS_WEIGHT + STARS_WEIGHT + FOLLOWERS_WEIGHT)
THRESHOLDS = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
LEVELS = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]


def exponential_cdf(x):
    return 1 - 2 ** -x


def log_normal_cdf(x):
    return x / (1 + x)


def calculate_rank(stats):
    rank = 1 - (
        COMMITS_WEIGHT * exponential_cdf(stats["commits"] / float(COMMITS_MEDIAN))
        + PRS_WEIGHT * exponential_cdf(stats["prs"] / float(PRS_MEDIAN))
        + ISSUES_WEIGHT * exponential_cdf(stats["issues"] / float(ISSUES_MEDIAN))
        + REVIEWS_WEIGHT * exponential_cdf(stats["reviews"] / float(REVIEWS_MEDIAN))
        + STARS_WEIGHT * log_normal_cdf(stats["stars"] / float(STARS_MEDIAN))
        + FOLLOWERS_WEIGHT * log_normal_cdf(stats["followers"] / float(FOLLOWERS_MEDIAN))
    ) / float(TOTAL_WEIGHT)
    percentile = rank * 100
    level = LEVELS[next(i for i, t in enumerate(THRESHOLDS) if percentile <= t)]
    return level, percentile


def gh(*args):
    r = subprocess.run(["gh", "api"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("gh api %s failed: %s"
                           % (" ".join(args), (r.stderr or r.stdout).strip()[:400]))
    return r.stdout


def fetch_stars_and_repos():
    """Sum stargazers over own non-fork repos; also return public repo count."""
    stars, total = 0, 0
    page = 1
    while True:
        repos = json.loads(gh("/users/%s/repos?per_page=100&page=%d&type=owner" % (USER, page)))
        if not repos:
            break
        for repo in repos:
            total += 1
            if not repo.get("fork"):
                stars += repo.get("stargazers_count", 0)
        if len(repos) < 100:
            break
        page += 1
    return stars, total


def fetch_contributions():
    """Commits and PR reviews via GraphQL, with a search-API fallback for commits."""
    query = ('query { user(login: "%s") { contributionsCollection '
             '{ totalCommitContributions totalPullRequestReviewContributions } '
             'followers { totalCount } } }' % USER)
    try:
        data = json.loads(gh("graphql", "-f", "query=" + query))["data"]["user"]
        coll = data["contributionsCollection"]
        return (coll["totalCommitContributions"],
                coll["totalPullRequestReviewContributions"],
                data["followers"]["totalCount"])
    except Exception as exc:  # noqa: BLE001
        print("GraphQL contributions failed (%s); falling back to search API" % exc)
        since = (date.today() - timedelta(days=365)).isoformat()
        commits = json.loads(gh("/search/commits?q=author:%s+committer-date:>%s&per_page=1"
                                % (USER, since)))["total_count"]
        followers = json.loads(gh("/users/%s" % USER))["followers"]
        return commits, 0, followers


def fetch_count(kind):
    """All-time authored PR / issue count via the search API."""
    return json.loads(gh("/search/issues?q=author:%s+type:%s&per_page=1"
                         % (USER, kind)))["total_count"]


def collect():
    stars, repos = fetch_stars_and_repos()
    commits, reviews, followers = fetch_contributions()
    stats = {
        "stars": stars,
        "commits": commits,
        "prs": fetch_count("pr"),
        "issues": fetch_count("issue"),
        "reviews": reviews,
        "followers": followers,
        "repos": repos,
    }
    level, percentile = calculate_rank(stats)
    stats["level"] = level
    stats["percentile"] = percentile
    return stats


THEMES = {
    "dark": dict(accent="#58a6ff", text="#c9d1d9"),
    "light": dict(accent="#0969da", text="#1f2328"),
}
W, H = 467, 195
ROWS = [
    ("Total Stars Earned:", "stars"),
    ("Total Commits (last year):", "commits"),
    ("Total PRs:", "prs"),
    ("Total Issues:", "issues"),
    ("Followers:", "followers"),
]


def build(stats, theme):
    t = THEMES[theme]
    # upstream draws the arc over a 250-unit path: dashoffset = 2.5 * percentile
    offset = 2.5 * stats["percentile"]
    p = []
    p.append('<svg width="%d" height="%d" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">'
             % (W, H, W, H))
    p.append('<style>.h{font:600 18px sans-serif;fill:%s}'
             '.s{font:600 14px sans-serif;fill:%s}'
             '.r{font:800 24px sans-serif;fill:%s}'
             '.c{stroke:%s;fill:none;stroke-width:6}</style>'
             % (t["accent"], t["text"], t["text"], t["accent"]))
    p.append('<rect x="0.5" y="0.5" width="%d" height="%d" rx="4.5" fill="#00000000"/>'
             % (W - 1, H - 1))
    p.append('<g transform="translate(25,35)"><text class="h">GitHub Overview</text></g>')
    p.append('<g transform="translate(0,55)">')
    p.append('<g transform="translate(390.5,47.5)">'
             '<circle class="c" opacity="0.2" cx="0" cy="0" r="40"/>'
             '<circle class="c" opacity="0.8" cx="0" cy="0" r="40" stroke-dasharray="250" '
             'transform="rotate(-90)" stroke-dashoffset="%.2f"/>'
             '<text x="0" y="0" class="r" text-anchor="middle" dominant-baseline="central">%s</text>'
             '</g>' % (offset, stats["level"]))
    for i, (label, key) in enumerate(ROWS):
        p.append('<g transform="translate(25,%d)">'
                 '<text x="0" y="12.5" class="s">%s</text>'
                 '<text x="219" y="12.5" class="s">%s</text></g>'
                 % (i * 25, label, format(stats[key], ",")))
    p.append('</g></svg>')
    return "".join(p)


def main():
    try:
        stats = collect()
    except Exception as exc:  # noqa: BLE001
        print("stats collection failed: %s" % exc, file=sys.stderr)
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    for theme in ("dark", "light"):
        svg = build(stats, theme)
        path = os.path.join(OUT_DIR, "github-stats-%s.svg" % theme)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        print("wrote %s (%d bytes)" % (path, len(svg)))
    print("stats: %s" % json.dumps({k: v for k, v in stats.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
