#!/usr/bin/env python3
"""Build the profile README figures and stat chips from live GitHub data.

Writes assets/{hero,metrics,pipeline}-{light,dark}.svg and rewrites the chips
between the stats markers in README.md. Stdlib only: all text in the SVGs is
drawn from glyph outlines in assets/glyphs.json, so no fonts are needed here or
in the viewer's browser. Output is deterministic; an unchanged set of numbers
produces byte-identical files. Any API failure or implausible number exits
non-zero before a single file is written.
"""
import datetime as dt
import json
import math
import os
import random
import re
import subprocess
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
USER = "Anuraj-dev"
REPO = "voisu"

THEMES = {
    "light": {"fg": "#1f2328", "muted": "#59636e", "border": "#d1d9e0", "sig": "#b85c00"},
    "dark": {"fg": "#f0f6fc", "muted": "#9198a1", "border": "#3d444d", "sig": "#f2a53a"},
}

# Release assets that count as downloads: installers and packages. Update
# manifests (latest*.json), checksums (SHA256SUMS*) and signatures are fetched
# by machines, not people, so they are left out.
INCLUDE = re.compile(r"\.(exe|msi|deb|rpm|apk|dmg|zip|AppImage|tar\.gz|tar\.xz|tar\.zst)$", re.I)
EXCLUDE = re.compile(r"(^latest.*\.json$|^SHA256SUMS|\.(sig|asc|minisig|sha256)$)", re.I)


def die(msg):
    print("build_readme: " + msg, file=sys.stderr)
    raise SystemExit(1)


# ───────────────────────── data ─────────────────────────

def token():
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        out = ""
    if not out:
        die("no GH_TOKEN/GITHUB_TOKEN and `gh auth token` gave nothing")
    return out


def graphql(tok, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": "Bearer " + tok, "User-Agent": USER + "-readme", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        die("GraphQL request failed: %s" % e)
    if body.get("errors") or not body.get("data"):
        die("GraphQL errors: %s" % json.dumps(body.get("errors"))[:500])
    return body["data"]


Q_USER = """query($login:String!){user(login:$login){contributionsCollection{
  totalPullRequestContributions contributionCalendar{totalContributions}}}}"""

Q_REPO = """query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
  defaultBranchRef{target{... on Commit{history{totalCount}}}}
  releases(first:100,after:$after,orderBy:{field:CREATED_AT,direction:DESC}){
    pageInfo{hasNextPage endCursor}
    nodes{tagName isDraft isPrerelease isLatest publishedAt releaseAssets(first:100){nodes{name downloadCount}}}}}}"""


def fetch(today):
    tok = token()
    cc = graphql(tok, Q_USER, {"login": USER})["user"]["contributionsCollection"]
    releases, after, commits = [], None, None
    while True:
        repo = graphql(tok, Q_REPO, {"owner": USER, "name": REPO, "after": after})["repository"]
        commits = repo["defaultBranchRef"]["target"]["history"]["totalCount"]
        releases += repo["releases"]["nodes"]
        if not repo["releases"]["pageInfo"]["hasNextPage"]:
            break
        after = repo["releases"]["pageInfo"]["endCursor"]

    published = [r for r in releases if not r["isDraft"] and r["publishedAt"]]
    if not published:
        die("no published releases of %s/%s" % (USER, REPO))
    latest = [r for r in published if r["isLatest"]] or sorted(
        (r for r in published if not r["isPrerelease"]), key=lambda r: r["publishedAt"]
    )[-1:]
    if not latest:
        die("no latest release")
    first = dt.date.fromisoformat(min(r["publishedAt"] for r in published)[:10])
    weeks = round((today - first).days / 7)

    downloads, inc, exc = 0, set(), set()
    for r in published:
        for a in r["releaseAssets"]["nodes"]:
            shape = re.sub(r"\d+", "N", a["name"])
            if INCLUDE.search(a["name"]) and not EXCLUDE.search(a["name"]):
                downloads += a["downloadCount"]
                inc.add(shape)
            else:
                exc.add(shape)
                if not EXCLUDE.search(a["name"]):
                    print("build_readme: warning: unrecognised asset %r not counted" % a["name"], file=sys.stderr)

    d = {
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "prs": cc["totalPullRequestContributions"],
        "releases": len(published),
        "version": latest[0]["tagName"].lstrip("v"),
        "weeks": weeks,
        "commits": commits,
        "downloads": downloads,
    }
    if d["contributions"] <= 0 or d["prs"] <= 0 or d["commits"] <= 0 or d["downloads"] <= 0:
        die("implausible numbers: %s" % d)
    if not re.fullmatch(r"\d+\.\d+\.\d+", d["version"]):
        die("unexpected release tag %r" % latest[0]["tagName"])
    print("downloads counted from: " + ", ".join(sorted(inc)))
    print("downloads excluded:     " + (", ".join(sorted(exc)) or "none"))
    return d


# ───────────────────────── glyphs ─────────────────────────

FONTS = json.loads((ASSETS / "glyphs.json").read_text(encoding="utf-8"))


def n(v, places=2):
    """Compact number for SVG attributes."""
    s = "%.*f" % (places, v)
    return s.rstrip("0").rstrip(".") if "." in s else s


class Glyphs:
    """Collects the outlines a figure uses and places them with <use>."""

    def __init__(self):
        self.used = {}

    def ref(self, font, ch):
        gid = "%s-%x" % (font, ord(ch))
        self.used[gid] = FONTS[font]["glyphs"][ch][1]
        return gid

    @staticmethod
    def adv(font, ch, size):
        f = FONTS[font]
        return f["glyphs"][ch][0] * size / f["upm"]

    def width(self, font, text, size, spacing=0.0):
        return sum(self.adv(font, c, size) for c in text) + spacing * size * (len(text) - 1)

    def one(self, font, ch, x, y, size, attrs=""):
        """One glyph with its left edge at x and its baseline at y."""
        k = size / FONTS[font]["upm"]
        return '<use href="#%s" transform="matrix(%s 0 0 -%s %s %s)"%s/>' % (self.ref(font, ch), n(k, 5), n(k, 5), n(x), n(y), attrs)

    def run(self, font, text, x, y, size, anchor="start", spacing=0.0, attrs=""):
        """A line of text as one scaled group; spacing is letter-spacing in em."""
        f = FONTS[font]
        w = self.width(font, text, size, spacing)
        x -= {"start": 0, "middle": w / 2, "end": w}[anchor]
        k = size / f["upm"]
        out, u = [], 0.0
        for c in text:
            if c != " ":
                out.append('<use href="#%s" x="%s"/>' % (self.ref(font, c), n(u)))
            u += f["glyphs"][c][0] + spacing * f["upm"]
        return '<g transform="translate(%s %s) scale(%s -%s)"%s>%s</g>' % (n(x), n(y), n(k, 5), n(k, 5), attrs, "".join(out))

    def defs(self):
        return "".join('<path id="%s" d="%s"/>' % (g, d) for g, d in sorted(self.used.items()))


def svg(w, h, label, css, body, theme, defs=""):
    t = THEMES[theme]
    for k, v in t.items():
        css = css.replace("@" + k, v)
        body = body.replace("@" + k, v)
        defs = defs.replace("@" + k, v)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-labelledby="t">'
        "<title id=\"t\">%s</title><style>%s</style><defs>%s</defs>%s</svg>\n" % (w, h, w, h, escape(label), css, defs, body)
    )


# ───────────────────────── hero ─────────────────────────

PHRASES = [
    "I build AI systems and ship them as products.",
    "Voice dictation in Rust, for Linux and Windows.",
    "Realtime video on my own mediasoup SFU.",
    "On-device Android apps in Kotlin.",
]
HERO_LABEL = "Anuraj-dev. I build AI systems and ship them as products. Voice dictation in Rust, realtime video, on-device Android."


def hero(d, theme):
    W, H = 846, 250
    rnd = random.Random(11)
    LOOP, STEP, PER, LEAD = 20.0, 0.045, 5.0, 0.5
    CW, X0, Y = 13.2, 1.0, 224
    g = Glyphs()

    pts = [(0.0, 0)]
    for k, p in enumerate(PHRASES):
        s = k * PER + LEAD
        pts += [(s - 0.35, 0), (s - 0.05, 1), (s + len(p) * STEP, 1), (s + len(p) * STEP + 0.4, 0)]
    pts.append((LOOP, 0))

    def kf(fn):
        return "".join("%.2f%%{%s}" % (t / LOOP * 100, fn(v)) for t, v in pts)

    css = [
        ".c{opacity:0;animation:ch 20s steps(1) infinite}",
        "@keyframes ch{0%{opacity:1}30%{opacity:1}30.01%{opacity:0}100%{opacity:0}}",
        ".ph{opacity:0;animation:ph 20s linear infinite}",
        "@keyframes ph{0%{opacity:1}22.4%{opacity:1}23.8%{opacity:0}100%{opacity:0}}",
        ".blink{fill:@sig;animation:blink 1s steps(1) infinite}",
        "@keyframes blink{0%{opacity:1}50%{opacity:0}}",
        ".b{fill:@sig;animation-timing-function:ease-in-out;animation-iteration-count:infinite;animation-direction:alternate}",
        ".j1{animation-name:j1}.j2{animation-name:j2}.j3{animation-name:j3}",
        "@keyframes j1{from{transform:scaleY(.3)}to{transform:scaleY(1)}}",
        "@keyframes j2{from{transform:scaleY(1)}to{transform:scaleY(.42)}}",
        "@keyframes j3{0%{transform:scaleY(.55)}50%{transform:scaleY(1)}100%{transform:scaleY(.25)}}",
        ".env{transform:scaleY(.16);opacity:.45;animation:env 20s ease-in-out infinite}",
        "@keyframes env{%s}" % kf(lambda v: "transform:scaleY(%s);opacity:%s" % ((1, 1) if v else (0.16, 0.45))),
        ".on{opacity:0;animation:on 20s ease-in-out infinite}.off{animation:off 20s ease-in-out infinite}",
        "@keyframes on{%s}" % kf(lambda v: "opacity:%d" % v),
        "@keyframes off{%s}" % kf(lambda v: "opacity:%d" % (1 - v)),
    ]

    bars = []
    for i in range(106):
        x = 1 + i * 8
        e = abs(math.sin(i * 0.19 + 0.4)) ** 1.5 * (0.55 + 0.45 * abs(math.sin(i * 0.047 + 1.3)))
        h = 6 + 54 * e * (0.65 + 0.35 * rnd.random())
        bars.append(
            '<rect class="b j%d" x="%d" y="%.1f" width="4" height="%.1f" rx="2" style="animation-duration:%.2fs;animation-delay:%.2fs"/>'
            % (rnd.randint(1, 3), x, -h / 2, h, 0.38 + rnd.random() * 0.6, -rnd.random() * 2)
        )

    groups = []
    for k, p in enumerate(PHRASES):
        s = k * PER + LEAD
        nch = len(p)
        css.append(
            ".cr%d{animation:cr%d 20s linear %.2fs infinite}"
            "@keyframes cr%d{0%%{transform:translateX(0);animation-timing-function:steps(%d,end)}%.3f%%{transform:translateX(%.1fpx)}100%%{transform:translateX(%.1fpx)}}"
            % (k, k, s, k, nch, nch * STEP / LOOP * 100, nch * CW, nch * CW)
        )
        chars = "".join(
            g.one("plex400", c, X0 + i * CW, Y, 22, ' class="c" style="animation-delay:%.3fs"' % (s + (i + 1) * STEP))
            for i, c in enumerate(p)
            if c != " "
        )
        groups.append(
            '<g class="ph ph%d" style="animation-delay:%.2fs">%s<g class="cr%d"><rect class="blink" x="%.1f" y="%d" width="10" height="25" rx="1.5"/></g></g>'
            % (k, s, chars, k, X0 + 1.5, Y - 20)
        )

    css.append(
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}.ph0,.ph0 .c{opacity:1}"
        ".ph0 .blink{opacity:0}.env{transform:scaleY(.6);opacity:1}}"
    )

    LS = 13  # status labels: 11px in the prototype, raised for phones
    body = (
        '<circle cx="5" cy="14" r="4" fill="@muted" class="off"/><circle cx="5" cy="14" r="4" fill="@sig" class="on"/>'
        + g.run("plex500", "READY", 17, 18.5, LS, spacing=0.09, attrs=' class="off" fill="@muted"')
        + g.run("plex500", "LISTENING", 17, 18.5, LS, spacing=0.09, attrs=' class="on" fill="@sig"')
        + g.run("plex500", "VOISU " + d["version"], 845, 18.5, LS, anchor="end", spacing=0.09, attrs=' fill="@muted"')
        + '<g transform="translate(0,74)"><g class="env">%s</g></g>' % "".join(bars)
        + g.run("mm800", "Anuraj-dev", -2, 172, 60, spacing=-0.03, attrs=' fill="@fg"')
        + '<g fill="@fg">%s</g>' % "".join(groups)
    )
    return svg(W, H, HERO_LABEL, "".join(css), body, theme, g.defs())


# ───────────────────────── metrics ─────────────────────────

def fmt(v):
    return "{:,}".format(v)


def metric_cells(d):
    rel = "voisu releases, %d weeks" % d["weeks"] if d["weeks"] <= 52 else "voisu releases"
    return [
        (fmt(d["contributions"]), "contributions, past year"),
        (fmt(d["prs"]), "pull requests, past year"),
        (fmt(d["releases"]), rel),
        (fmt(d["downloads"]), "voisu downloads"),
    ]


def metrics(d, theme):
    W, H = 846, 92
    LH, DW, COMMA, BASE, TOP, SIZE = 44, 25, 13, 42, 6, 34
    cells = metric_cells(d)
    g = Glyphs()
    gw = g.adv("mm600", "0", SIZE)
    css = [".od{animation-duration:11s;animation-timing-function:cubic-bezier(.3,.9,.25,1);animation-iteration-count:infinite}"]
    for k in range(10):
        css.append(
            ".od%d{transform:translateY(-%dpx);animation-name:od%d}"
            "@keyframes od%d{0%%{transform:translateY(-%dpx)}12%%,100%%{transform:translateY(-%dpx)}}"
            % (k, k * LH, k, k, k * LH, (k + 10) * LH)
        )
    css.append("@media (prefers-reduced-motion:reduce){.od{animation:none!important}}")

    # One strip of 0-9 twice over, stacked LH apart; every odometer cell reuses it.
    strip = '<g id="strip">%s</g>' % "".join(g.one("mm600", str(j % 10), 0, j * LH, SIZE) for j in range(20))
    clips, out, idx = [], [], 0
    cw = W / len(cells)
    for i, (num, label) in enumerate(cells):
        x0 = i * cw + (0 if i == 0 else 12)  # 22 in the prototype; 13px labels need the room
        if i:
            out.append('<line x1="%s" y1="8" x2="%s" y2="84" stroke="@border" stroke-width="1"/>' % (n(i * cw), n(i * cw)))
        x = x0
        for ch in num:
            if ch == ",":
                out.append(g.one("mm600", ",", x + COMMA / 2 - 1 - gw / 2, BASE, SIZE))
                x += COMMA
                continue
            clips.append('<clipPath id="k%d"><rect x="%s" y="%d" width="%d" height="%d"/></clipPath>' % (idx, n(x), TOP, DW, LH))
            out.append(
                '<g clip-path="url(#k%d)"><g class="od od%s" style="animation-delay:%.2fs"><use href="#strip" x="%s" y="%d"/></g></g>'
                % (idx, ch, 0.5 + idx * 0.07, n(x + DW / 2 - gw / 2), BASE)
            )
            x += DW
            idx += 1
        out.append(g.run("plex400", label, x0 + 2, 76, 13, attrs=' fill="@muted"'))
    label = "; ".join("%s %s" % c for c in cells)
    body = '<g fill="@fg">%s</g>' % "".join(out)
    return svg(W, H, label, "".join(css), body, theme, g.defs() + strip + "".join(clips))


# ───────────────────────── pipeline ─────────────────────────

PIPE_LABEL = (
    "How voisu works: your voice goes to Deepgram, which streams while you talk, and to Groq Whisper, which "
    "transcribes the whole recording on release. voisu reconciles the two and puts the text at your cursor."
)


def pipeline(theme):
    top = "M110,75 C150,75 150,35 195,35 L533,35 C578,35 578,75 618,75"
    bot = "M110,75 C150,75 150,115 195,115 L533,115 C578,115 578,75 618,75"
    D4 = "4.8s"
    S = 13
    g = Glyphs()
    css = (
        ".lane,.node{fill:none;stroke:@border;stroke-width:1.5}"
        ".hot{fill:none;stroke:@sig;stroke-width:1.5}"
        ".dot{fill:@sig}"
        "@media (prefers-reduced-motion:reduce){.mv{display:none}}"
    )

    def lane_label(head, tail, y):
        w1, w2 = g.width("plex500", head, S), g.width("plex400", tail, S)
        x = 364 - (w1 + w2) / 2
        return g.run("plex500", head, x, y, S, attrs=' fill="@fg"') + g.run("plex400", tail, x + w1, y, S, attrs=' fill="@muted"')

    stream = "".join(
        '<circle class="dot mv" r="2.6"><animateMotion dur="2.4s" begin="-%.2fs" repeatCount="indefinite" path="%s"/></circle>' % (i * 0.48, top)
        for i in range(5)
    )
    packet = (
        '<circle class="dot mv" r="5" opacity="0">'
        '<animateMotion dur="%s" repeatCount="indefinite" calcMode="linear" keyPoints="0;0;1;1" keyTimes="0;0.5;0.74;1" path="%s"/>'
        '<animate attributeName="opacity" dur="%s" repeatCount="indefinite" values="0;0;1;1;0;0" keyTimes="0;0.49;0.5;0.74;0.76;1"/></circle>'
        % (D4, bot, D4)
    )
    pulse = (
        '<rect class="hot mv" x="618" y="57" width="96" height="36" rx="6" opacity="0">'
        '<animate attributeName="opacity" dur="%s" repeatCount="indefinite" values="0;0;1;0;0" keyTimes="0;0.73;0.77;0.93;1"/></rect>' % D4
    )
    hop = (
        '<circle class="dot mv" r="3" opacity="0">'
        '<animateMotion dur="%s" repeatCount="indefinite" calcMode="linear" keyPoints="0;0;1;1" keyTimes="0;0.8;0.88;1" path="M714,75 L738,75"/>'
        '<animate attributeName="opacity" dur="%s" repeatCount="indefinite" values="0;0;1;1;0;0" keyTimes="0;0.79;0.8;0.87;0.88;1"/></circle>' % (D4, D4)
    )
    flash = (
        '<rect class="mv" x="740" y="57" width="105" height="36" rx="18" fill="@sig" opacity="0">'
        '<animate attributeName="opacity" dur="%s" repeatCount="indefinite" values="0;0;.28;0;0" keyTimes="0;0.87;0.9;0.99;1"/></rect>' % D4
    )
    node = dict(attrs=' fill="@fg"', anchor="middle")
    body = (
        '<path class="lane" d="%s"/><path class="lane" d="%s"/>' % (top, bot)
        + '<line x1="714" y1="75" x2="733" y2="75" stroke="@border" stroke-width="1.5"/>'
        '<polygon points="732,70.5 740,75 732,79.5" fill="@muted"/>'
        '<rect class="node" x="1" y="57" width="109" height="36" rx="18"/>'
        + g.run("plex500", "your voice", 55.5, 79.5, S, **node)
        + '<rect class="node" x="618" y="57" width="96" height="36" rx="6"/>'
        + g.run("plex500", "reconcile", 666, 79.5, S, **node)
        + flash
        + stream
        + '<rect class="hot" x="740" y="57" width="105" height="36" rx="18"/>'
        + g.run("plex500", "your cursor", 792.5, 79.5, S, **node)
        + lane_label("Deepgram", " · streams while you talk", 21)
        + lane_label("Groq Whisper", " · whole recording, on release", 139)
        + packet
        + pulse
        + hop
    )
    return svg(846, 150, PIPE_LABEL, css, body, theme, g.defs())


# ───────────────────────── README chips ─────────────────────────

def chips(d):
    return (
        "`%s downloads` `%s releases` `%s commits` `MIT` "
        "Fedora COPR · AUR · apt · Windows installer · or fully local on Linux"
        % (fmt(d["downloads"]), fmt(d["releases"]), fmt(d["commits"]))
    )


def main():
    today = dt.date.today()
    d = fetch(today)
    print("numbers: " + json.dumps(d, sort_keys=True))

    readme = README.read_text(encoding="utf-8")
    pat = re.compile(r"(<!-- stats:start -->).*?(<!-- stats:end -->)", re.S)
    if not pat.search(readme):
        die("stats markers not found in README.md")
    files = {README: pat.sub(lambda m: m.group(1) + "\n" + chips(d) + "\n" + m.group(2), readme, count=1)}
    for theme in THEMES:
        files[ASSETS / ("hero-%s.svg" % theme)] = hero(d, theme)
        files[ASSETS / ("metrics-%s.svg" % theme)] = metrics(d, theme)
        files[ASSETS / ("pipeline-%s.svg" % theme)] = pipeline(theme)

    for path, text in files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            print("wrote " + str(path.relative_to(ROOT)))


if __name__ == "__main__":
    main()
