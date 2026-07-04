#!/usr/bin/env python3
"""Render a deep-space profile banner where the STATS are the hero.

A beautiful space scene (Milky Way, nebulae, a supermassive black hole with a
tilted accretion disk, orbiting language "worlds", a rocket, a supernova) — but
the numbers are the brightest objects in the frame: a huge glowing contribution
count and a bold vitals grid, so anyone landing on the profile instantly reads
"here's what he's been doing."

Data (repos, languages, contributions, commits, PRs) comes from the GitHub
GraphQL API via the `gh` CLI, so it works locally when you're logged in and in
CI with the default GITHUB_TOKEN. Output is one self-contained, gently animated
SVG that GitHub caches — no third-party widgets — refreshed nightly by an Action.
"""
import datetime as dt
import json
import math
import random
import subprocess
import sys
import xml.sax.saxutils as _xml
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
USER = "Anuraj-dev"
TODAY = dt.date.today()

W, H = 900, 420

# ---- palette: deep space ----
BG_TOP, BG_BOT = "#060a16", "#02040a"
STAR_COLORS = ["#ffffff", "#dbe7ff", "#cfe0ff", "#cfe0ff",
               "#fff3d6", "#ffe6c7", "#e7d6ff"]
TEXT_HI = "#eef3ff"
TEXT = "#c2cee4"
TEXT_MUTED = "#8ea3c6"
TEXT_DIM = "#5a6a89"
CYAN = "#5ee7ff"
ICE = "#bfe9ff"
VIOLET = "#a78bfa"
ROSE = "#fb7ba8"
ORANGE = "#ffb454"
GOLD = "#ffe6a8"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

GQL = """
query($login:String!){
  user(login:$login){
    name login createdAt
    followers{ totalCount }
    repositories(first:100, ownerAffiliations:OWNER, isFork:false){
      totalCount
      nodes{
        stargazerCount forkCount
        languages(first:8, orderBy:{field:SIZE, direction:DESC}){
          edges{ size node{ name color } }
        }
      }
    }
    contributionsCollection{
      totalCommitContributions totalPullRequestContributions
      contributionCalendar{
        totalContributions
        weeks{ contributionDays{ date contributionCount } }
      }
    }
  }
}
"""


def fetch():
    proc = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={GQL}", "-f", f"login={USER}"],
        text=True, capture_output=True)
    if proc.returncode != 0:
        print("gh api graphql failed:\n" + proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    return json.loads(proc.stdout)["data"]["user"]


def pretty_date(iso, short=False):
    d = dt.date.fromisoformat(iso[:10])
    return f"{MONTHS[d.month-1]} {d.year}" if short \
        else f"{MONTHS[d.month-1]} {d.day}, {d.year}"


def compute(u):
    repos = u["repositories"]["nodes"]
    lang_bytes, lang_color = defaultdict(int), {}
    for r in repos:
        for e in r["languages"]["edges"]:
            lang_bytes[e["node"]["name"]] += e["size"]
            lang_color[e["node"]["name"]] = e["node"]["color"] or "#8892b0"
    total = sum(lang_bytes.values()) or 1
    langs = [{"name": n, "pct": 100 * b / total, "color": lang_color[n]}
             for n, b in sorted(lang_bytes.items(), key=lambda kv: -kv[1])]

    cc = u["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]]
    best = max(days, key=lambda d: d["contributionCount"])
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)

    return {
        "name": u["name"] or u["login"],
        "login": u["login"],
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "prs": cc["totalPullRequestContributions"],
        "repos": u["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "lang_count": len(langs),
        "langs": langs,
        "active_days": sum(1 for d in days if d["contributionCount"] > 0),
        "window_days": len(days),
        "longest_streak": longest,
        "biggest_day": best["contributionCount"],
        "biggest_date": pretty_date(best["date"]).rsplit(",", 1)[0],
        "born": pretty_date(u["createdAt"]),
        "generated": TODAY.isoformat(),
    }


# ---------------------------------------------------------------------------
def esc(s):
    return _xml.escape(str(s))


def txt(x, y, s, size=12, fill=TEXT, weight=400, family="sans",
        anchor="start", spacing=None, italic=False, opacity=None, glow=False):
    fam = {
        "mono": "ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace",
        "serif": "'Iowan Old Style',Palatino,Georgia,'Times New Roman',serif",
        "sans": "'Segoe UI',system-ui,-apple-system,Helvetica,Arial,sans-serif",
    }[family]
    a = f' letter-spacing="{spacing}"' if spacing else ""
    it = ' font-style="italic"' if italic else ""
    o = f' opacity="{opacity}"' if opacity is not None else ""
    fl = ' filter="url(#glow)"' if glow else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-size="{size}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"'
            f'{a}{it}{o}{fl}>{esc(s)}</text>')


def stat(x, y, value, label, num_size=29, accent=TEXT_MUTED):
    """A bold glowing number with a small caps label beneath it."""
    return (txt(x, y, value, size=num_size, fill=TEXT_HI, weight=800,
                family="sans", glow=True)
            + txt(x, y + 15, label, size=8.5, fill=accent, family="sans",
                  spacing="1.5"))


def build_svg(d):
    rnd = random.Random(11)  # fixed seed → stable sky, no daily git churn
    S = []
    S.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="{esc(d["login"])} — GitHub in deep space">')

    # ---- defs ----
    S.append('<defs>')
    S.append(f'<linearGradient id="sky" x1="0" y1="0" x2="0.3" y2="1">'
             f'<stop offset="0" stop-color="{BG_TOP}"/>'
             f'<stop offset="1" stop-color="{BG_BOT}"/></linearGradient>')
    S.append('<radialGradient id="neb_v" cx="0.16" cy="0.3" r="0.5">'
             f'<stop offset="0" stop-color="{VIOLET}" stop-opacity="0.30"/>'
             f'<stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/></radialGradient>')
    S.append('<radialGradient id="neb_r" cx="0.9" cy="0.2" r="0.5">'
             f'<stop offset="0" stop-color="{ROSE}" stop-opacity="0.24"/>'
             f'<stop offset="1" stop-color="{ROSE}" stop-opacity="0"/></radialGradient>')
    S.append('<linearGradient id="milky" x1="0" y1="1" x2="1" y2="0">'
             '<stop offset="0" stop-color="#5a6ea8" stop-opacity="0"/>'
             '<stop offset="0.5" stop-color="#aeb9e6" stop-opacity="0.15"/>'
             '<stop offset="1" stop-color="#5a6ea8" stop-opacity="0"/></linearGradient>')
    S.append('<radialGradient id="bhglow" cx="0.5" cy="0.5" r="0.5">'
             f'<stop offset="0" stop-color="{ORANGE}" stop-opacity="0.5"/>'
             f'<stop offset="0.55" stop-color="{VIOLET}" stop-opacity="0.16"/>'
             f'<stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/></radialGradient>')
    S.append('<radialGradient id="hole" cx="0.5" cy="0.5" r="0.5">'
             '<stop offset="0.6" stop-color="#000005"/>'
             '<stop offset="0.86" stop-color="#05030a"/>'
             f'<stop offset="1" stop-color="{VIOLET}" stop-opacity="0.9"/></radialGradient>')
    S.append('<radialGradient id="nova" cx="0.5" cy="0.5" r="0.5">'
             '<stop offset="0" stop-color="#ffffff"/>'
             f'<stop offset="0.4" stop-color="{GOLD}"/>'
             f'<stop offset="1" stop-color="{ROSE}" stop-opacity="0"/></radialGradient>')
    # darkening behind the stat zone so the bright numbers pop
    S.append('<radialGradient id="statdark" cx="0.5" cy="0.5" r="0.5">'
             '<stop offset="0" stop-color="#01030a" stop-opacity="0.6"/>'
             '<stop offset="0.7" stop-color="#01030a" stop-opacity="0.42"/>'
             '<stop offset="1" stop-color="#01030a" stop-opacity="0"/></radialGradient>')
    # soft glow for the hero numbers
    S.append('<filter id="glow" x="-30%" y="-30%" width="160%" height="160%">'
             '<feGaussianBlur stdDeviation="2.1" result="b"/>'
             '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/>'
             '</feMerge></filter>')
    S.append('</defs>')

    # ---- sky + nebulae ----
    S.append(f'<rect width="{W}" height="{H}" rx="18" fill="url(#sky)"/>')
    for nid in ("neb_v", "neb_r"):
        S.append(f'<rect width="{W}" height="{H}" rx="18" fill="url(#{nid})"/>')

    def band_y(x):
        return 320 - 200 * (x / W)
    S.append(f'<g transform="rotate(-18 {W/2} {H/2})" opacity="0.9">'
             f'<ellipse cx="{W/2}" cy="{H/2}" rx="640" ry="66" '
             f'fill="url(#milky)"/></g>')

    # ---- starfield (deterministic; sparser on the right where the stats live)
    for i in range(170):
        along = rnd.random() < 0.5
        x = rnd.uniform(8, W - 8)
        y = band_y(x) + rnd.gauss(0, 28) if along else rnd.uniform(8, H - 8)
        y = min(max(y, 6), H - 6)
        # thin out stars over the stat panel so numbers stay clean
        if x > 380 and 96 < y < 350 and rnd.random() < 0.55:
            continue
        r = rnd.choice([0.5, 0.6, 0.7, 0.8, 0.8, 1.0, 1.2])
        op = rnd.uniform(0.22, 0.9)
        col = rnd.choice(STAR_COLORS)
        c = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}" opacity="{op:.2f}">'
        if i % 12 == 0:
            c += (f'<animate attributeName="opacity" values="{op:.2f};'
                  f'{op*0.2:.2f};{op:.2f}" dur="{3+(i%6)}s" repeatCount="indefinite"/>')
        c += '</circle>'
        S.append(c)

    # a couple of shooting stars
    for begin, path in [("5s;17s", "150,70;380,180"), ("11s;24s", "80,150;300,260")]:
        S.append(
            f'<g opacity="0"><line x1="0" y1="0" x2="28" y2="11" '
            f'stroke="{ICE}" stroke-width="1.2" stroke-linecap="round"/>'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="{path}" dur="1.3s" begin="{begin}" repeatCount="1" additive="sum"/>'
            f'<animate attributeName="opacity" values="0;0.9;0" dur="1.3s" '
            f'begin="{begin}" repeatCount="1"/></g>')

    # ================= SUPERMASSIVE BLACK HOLE (left feature) =================
    bx, by = 176, 208
    S.append(f'<circle cx="{bx}" cy="{by}" r="110" fill="url(#bhglow)"/>')
    tilt = f'transform="translate({bx} {by}) rotate(-20) scale(1 0.4)"'
    S.append(f'<g {tilt}>')
    for rr, col, op, wdt in [(25, "#ffffff", 0.95, 3), (29, ORANGE, 0.95, 5),
                             (35, GOLD, 0.8, 3.5), (44, CYAN, 0.6, 2.5),
                             (56, VIOLET, 0.38, 2)]:
        S.append(f'<circle r="{rr}" fill="none" stroke="{col}" '
                 f'stroke-width="{wdt}" opacity="{op}"/>')
    S.append(f'<circle r="49" fill="none" stroke="{ICE}" stroke-width="1" '
             f'stroke-dasharray="2 8" opacity="0.55">'
             f'<animateTransform attributeName="transform" type="rotate" '
             f'from="0" to="360" dur="26s" repeatCount="indefinite"/></circle>')
    orbits = [66, 82, 100, 120, 140, 158]
    worlds = d["langs"][:6]
    for r in orbits[:len(worlds)]:
        S.append(f'<circle r="{r}" fill="none" stroke="#43597f" '
                 f'stroke-width="1" stroke-dasharray="1 7" opacity="0.5"/>')
    for i, lang in enumerate(worlds):
        r = orbits[i]
        a = math.radians(35 + i * 58)
        px, py = r * math.cos(a), r * math.sin(a)
        pr = 4 + 11 * math.sqrt(lang["pct"] / 100)
        S.append(
            f'<g><animateTransform attributeName="transform" type="rotate" '
            f'from="0" to="360" dur="{34+i*12}s" repeatCount="indefinite"/>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{pr+3:.1f}" fill="{lang["color"]}" opacity="0.22"/>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{pr:.1f}" fill="{lang["color"]}" '
            f'stroke="#0a1120" stroke-width="0.8"/></g>')
    S.append('</g>')
    S.append(f'<circle cx="{bx}" cy="{by}" r="19" fill="url(#hole)"/>')
    S.append(f'<circle cx="{bx}" cy="{by}" r="19.5" fill="none" '
             f'stroke="{GOLD}" stroke-width="2.4" opacity="0.95"/>')
    S.append(f'<circle cx="{bx}" cy="{by}" r="21" fill="none" '
             f'stroke="{CYAN}" stroke-width="1" opacity="0.7"/>')

    # rocket swinging past the black hole (gravity assist)
    rk = ('<g>'
          f'<path d="M-10,-2.4 L-26,0 L-10,2.4 Z" fill="{ORANGE}" opacity="0.85">'
          f'<animate attributeName="opacity" values="0.85;0.35;0.85" dur="0.5s" '
          f'repeatCount="indefinite"/></path>'
          f'<path d="M-10,-1.3 L-19,0 L-10,1.3 Z" fill="{GOLD}"/>'
          f'<path d="M-10,-3.4 L4,-3.4 L11,0 L4,3.4 L-10,3.4 Z" fill="#e8eef7"/>'
          f'<path d="M4,-3.4 L11,0 L4,3.4 Z" fill="#c3d0e6"/>'
          f'<path d="M-10,-3.4 L-14,-7 L-6,-3.4 Z" fill="#9fb0cc"/>'
          f'<path d="M-10,3.4 L-14,7 L-6,3.4 Z" fill="#9fb0cc"/>'
          f'<circle cx="0" cy="0" r="1.7" fill="{CYAN}"/></g>')
    S.append(f'<g opacity="0.95"><g>{rk}'
             f'<animateMotion dur="30s" repeatCount="indefinite" rotate="auto" '
             f'path="M-60,340 Q30,240 150,150 Q250,80 380,70"/></g></g>')

    # ================= SUPERNOVA (busiest day) — top-right accent ============
    nx, ny = 838, 92
    for begin in ("0s", "1.6s"):
        S.append(f'<circle cx="{nx}" cy="{ny}" r="4" fill="none" stroke="{ROSE}" '
                 f'stroke-width="1.4"><animate attributeName="r" values="4;30" '
                 f'dur="3.2s" begin="{begin}" repeatCount="indefinite"/>'
                 f'<animate attributeName="opacity" values="0.85;0" dur="3.2s" '
                 f'begin="{begin}" repeatCount="indefinite"/></circle>')
    S.append(f'<circle cx="{nx}" cy="{ny}" r="22" fill="url(#nova)" opacity="0.9"/>')
    S.append(f'<g transform="translate({nx} {ny})" stroke="#fff" opacity="0.9">'
             f'<line x1="-12" y1="0" x2="12" y2="0" stroke-width="1.3"/>'
             f'<line x1="0" y1="-12" x2="0" y2="12" stroke-width="1.3"/>'
             f'<line x1="-7" y1="-7" x2="7" y2="7" stroke-width="0.6"/>'
             f'<line x1="-7" y1="7" x2="7" y2="-7" stroke-width="0.6"/>'
             f'<animate attributeName="opacity" values="1;0.55;1" dur="3s" '
             f'repeatCount="indefinite"/></g>')
    S.append(txt(nx - 30, ny - 3, "supernova", size=11, fill=GOLD,
                 family="serif", italic=True, anchor="end"))
    S.append(txt(nx - 30, ny + 11, f"{d['biggest_day']} commits · {d['biggest_date']}",
                 size=9, fill=TEXT_MUTED, family="mono", anchor="end"))

    # ================= NAME (top-left) =======================================
    S.append(txt(30, 44, d["name"], size=20, fill=TEXT_HI, weight=700))
    S.append(txt(31, 63, "building among the stars", size=12,
                 fill=TEXT, family="serif", italic=True))

    # ================= THE STATS — the hero of the frame =====================
    S.append('<ellipse cx="605" cy="215" rx="330" ry="180" fill="url(#statdark)"/>')

    # giant hero number: contributions
    S.append(txt(392, 176, f"{d['contributions']:,}", size=62, fill=TEXT_HI,
                 weight=800, glow=True))
    S.append(txt(396, 199, "CONTRIBUTIONS IN THE LAST YEAR", size=11,
                 fill=CYAN, spacing="2.5"))

    # bold vitals grid (2 rows × 3)
    colx = [396, 574, 752]
    row1 = [("commits", "COMMITS", CYAN), ("prs", "PULL REQUESTS", CYAN),
            ("repos", "REPOSITORIES", CYAN)]
    row2 = [("lang_count", "LANGUAGES", VIOLET),
            ("longest_streak", "LONGEST STREAK", VIOLET),
            ("active_days", "ACTIVE DAYS", VIOLET)]
    for cx_, (key, label, accent) in zip(colx, row1):
        val = f"{d[key]:,}"
        S.append(stat(cx_, 262, val, label, num_size=30, accent=TEXT_MUTED))
    for cx_, (key, label, accent) in zip(colx, row2):
        val = f"{d[key]}d" if key == "longest_streak" else f"{d[key]:,}"
        S.append(stat(cx_, 322, val, label, num_size=30, accent=TEXT_MUTED))

    # ================= LANGUAGES — bright legend row along the bottom ========
    S.append(txt(30, 372, "LANGUAGES", size=8.5, fill=TEXT_DIM, spacing="2"))
    lx = 30
    for lang in worlds:
        S.append(f'<circle cx="{lx+5}" cy="{392-4}" r="5" fill="{lang["color"]}"/>')
        S.append(f'<circle cx="{lx+5}" cy="{392-4}" r="7.5" fill="none" '
                 f'stroke="{lang["color"]}" stroke-width="0.8" opacity="0.35"/>')
        name = lang["name"]
        S.append(txt(lx + 16, 392, name, size=11, fill=TEXT_HI))
        nx2 = lx + 16 + len(name) * 6.6 + 6
        S.append(txt(nx2, 392, f"{lang['pct']:.0f}%", size=11, fill=lang["color"],
                     weight=600, family="mono"))
        lx = nx2 + 34

    # first light (account birth) — subtle, far bottom-right
    S.append(txt(W - 30, 392, f"✦ first light · {d['born']}", size=9.5,
                 fill=TEXT_DIM, anchor="end", family="serif", italic=True))

    S.append('</svg>')
    return "\n".join(S)


def main():
    data = compute(fetch())
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "space.svg").write_text(build_svg(data), encoding="utf-8")
    (ASSETS / "space.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("wrote assets/space.svg  —",
          f"{data['contributions']} contributions · {data['commits']} commits · "
          f"{data['prs']} PRs · {data['repos']} repos · {data['lang_count']} languages")


if __name__ == "__main__":
    main()
