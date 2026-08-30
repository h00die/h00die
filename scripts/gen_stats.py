#!/usr/bin/env python3
"""generate self-contained profile stats SVGs.

run locally (uses your gh auth) or via .github/workflows/stats.yml (uses GITHUB_TOKEN).
writes assets/stats.svg and assets/languages.svg. no third-party card service involved -
github-readme-stats.vercel.app keeps 503ing, so we render our own.

usage: STATS_USER=h00die GH_TOKEN=... python3 scripts/gen_stats.py
"""
import json
import os
import subprocess
import sys
from collections import Counter

USER = os.environ.get("STATS_USER", "h00die")
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

# page accent + github dark palette (matches streak card)
BG, TEXT, MUTED, ACCENT, BAR_BG = "#0d1117", "#e6edf3", "#8b949e", "#6BF178", "#21262d"

# linguist colors for the usual suspects; unknown langs fall back to gray
LANG_COLORS = {
    "Python": "#3572A0", "Ruby": "#701516", "C": "#555555", "C++": "#f34b7d",
    "Shell": "#89e051", "HTML": "#e34c26", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "Go": "#00ADD8", "Rust": "#dea584",
    "Java": "#b07219", "Kotlin": "#A97BFF", "C#": "#178600",
    "Dockerfile": "#384d54", "PowerShell": "#012456", "SCSS": "#c6538c",
    "CSS": "#563d7c", "Vue": "#41b883", "MDX": "#fcb32c", "HCL": "#844FBA",
}


def gh(*args):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[x] gh api {' '.join(args)}: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout)


def fetch_stats():
    user = gh(f"users/{USER}")
    repos, page = [], 1
    while True:
        batch = gh(f"users/{USER}/repos?per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1

    owned = [r for r in repos if not r.get("fork")]
    stars = sum(r.get("stargazers_count", 0) for r in owned)
    langs = Counter(r["language"] for r in owned if r.get("language"))

    contribs = 0
    q = subprocess.run(
        ["gh", "api", "graphql", "-f",
         f'query={{user(login:"{USER}"){{contributionsCollection{{contributionCalendar{{totalContributions}}}}}}}}'],
        capture_output=True, text=True)
    if q.returncode == 0:
        try:
            contribs = json.loads(q.stdout)["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        except (KeyError, TypeError, json.JSONDecodeError):
            pass

    return {
        "followers": user.get("followers", 0),
        "stars": stars,
        "repos": user.get("public_repos", 0),
        "contribs": contribs,
        "langs": langs.most_common(6),
    }


def svg_esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_stats(s):
    rows = [
        ("followers", f"{s['followers']:,}"),
        ("stars earned", f"{s['stars']:,}"),
        ("public repos", f"{s['repos']:,}"),
        ("contributions (1y)", f"{s['contribs']:,}"),
    ]
    body = [f'<text x="20" y="34" fill="{ACCENT}" font-size="15" font-weight="bold">{svg_esc(USER)}&#39;s github stats</text>']
    y = 64
    for label, value in rows:
        body.append(f'<text x="20" y="{y}" fill="{MUTED}" font-size="12">{svg_esc(label)}</text>')
        body.append(f'<text x="390" y="{y}" fill="{TEXT}" font-size="14" font-weight="bold" text-anchor="end">{svg_esc(value)}</text>')
        y += 34
    body.append(f'<text x="20" y="192" fill="#484f58" font-size="9" font-style="italic">self-generated daily by my own action - no third-party card service</text>')
    return svg_wrap(410, 200, body)


def render_langs(s):
    total = sum(n for _, n in s["langs"]) or 1
    body = [f'<text x="20" y="34" fill="{ACCENT}" font-size="15" font-weight="bold">top languages (by repo)</text>']
    y = 62
    for lang, count in s["langs"]:
        pct = round(count / total * 100)
        color = LANG_COLORS.get(lang, "#8b949e")
        body.append(f'<text x="20" y="{y}" fill="{TEXT}" font-size="12">{svg_esc(lang)}</text>')
        body.append(f'<rect x="130" y="{y - 9}" width="200" height="9" rx="4" fill="{BAR_BG}" />')
        body.append(f'<rect x="130" y="{y - 9}" width="{max(6, round(200 * pct / 100))}" height="9" rx="4" fill="{color}" />')
        body.append(f'<text x="390" y="{y}" fill="{MUTED}" font-size="12" text-anchor="end">{pct}%</text>')
        y += 28
    return svg_wrap(410, 200, body)


def svg_wrap(w, h, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Segoe UI, Helvetica, Arial, sans-serif">\n'
        f'<rect width="{w}" height="{h}" rx="6" fill="{BG}" />\n'
        + "\n".join(body) + "\n</svg>\n"
    )


def fetch_prs():
    """all PRs authored by USER in repos they don't own. search API caps at 1000 results.
    friends' metasploit-framework forks are module collab staging grounds, not real
    upstreams - they get their own group. only rapid7's is upstream."""
    q = f"author:{USER}+type:pr+-user:{USER}"
    items, page = [], 1
    while page <= 10:
        batch = gh(f"search/issues?q={q}&per_page=100&page={page}")
        items += batch.get("items", [])
        if len(items) >= batch.get("total_count", 0) or not batch.get("items"):
            break
        page += 1

    def is_collab(repo):
        return repo.endswith("/metasploit-framework") and repo != "rapid7/metasploit-framework"

    upstream, collabs = {}, {}
    for it in items:
        repo = it["repository_url"].split("/repos/")[-1]
        repos = collabs if is_collab(repo) else upstream
        r = repos.setdefault(repo, {"prs": 0, "merged": 0})
        r["prs"] += 1
        if (it.get("pull_request") or {}).get("merged_at"):
            r["merged"] += 1
    return upstream, collabs, len(items)


def prs_table(repos):
    lines = ["| repo | PRs | merged |", "| --- | --- | --- |"]
    for repo, r in sorted(repos.items(), key=lambda kv: (-kv[1]["prs"], kv[0])):
        lines.append(f"| [{repo}](https://github.com/{repo}) | {r['prs']} | {r['merged']} |")
    return lines


def render_prs_md(upstream, collabs, fetched):
    up_total = sum(r["prs"] for r in upstream.values())
    co_total = sum(r["prs"] for r in collabs.values())
    lines = [
        f"**{up_total} upstream PRs** to **{len(upstream)} external repos**"
        f" (repos i don't own), plus **{co_total} collab PRs** in friends' forks",
        "",
        *prs_table(upstream),
        "",
        "### collaborations",
        "",
        "metasploit module work usually starts in friends' forks before it lands upstream:",
        "",
        *prs_table(collabs),
    ]
    if up_total + co_total > fetched:
        lines.append(f"\n(github's search API caps at 1000 results; showing {fetched})")
    return "\n".join(lines)


def splice_readme(content):
    path = os.path.join(os.path.dirname(ASSETS), "README.md")
    start, end = "<!-- prs:start -->", "<!-- prs:end -->"
    text = open(path).read()
    if start not in text or end not in text:
        print("[x] README prs markers missing", file=sys.stderr)
        sys.exit(1)
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    open(path, "w").write(pre + start + "\n" + content + "\n" + end + post)
    print(f"[+] spliced prs section into {path}")


def main():
    os.makedirs(ASSETS, exist_ok=True)
    s = fetch_stats()
    for name, svg in (("stats", render_stats(s)), ("languages", render_langs(s))):
        path = os.path.join(ASSETS, f"{name}.svg")
        with open(path, "w") as f:
            f.write(svg)
        print(f"[+] wrote {path} ({os.path.getsize(path)} bytes)")
    splice_readme(render_prs_md(*fetch_prs()))


if __name__ == "__main__":
    main()
