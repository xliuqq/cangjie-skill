#!/usr/bin/env python3
"""Generate a self-hosted star-history SVG using the GitHub API."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape


GITHUB_API = "https://api.github.com"


def github_get(path: str, token: str) -> object:
    request = urllib.request.Request(
        f"{GITHUB_API}{path}",
        headers={
            "Accept": "application/vnd.github.star+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "cangjie-skill-star-history",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {message}") from exc


def fetch_star_dates(repo: str, token: str) -> list[dt.date]:
    repo_data = github_get(f"/repos/{repo}", token)
    if not isinstance(repo_data, dict) or not isinstance(repo_data.get("stargazers_count"), int):
        raise RuntimeError("Unexpected response from GitHub's repository API")

    page_count = max(math.ceil(repo_data["stargazers_count"] / 100), 1)

    def fetch_page(page: int) -> object:
        return github_get(f"/repos/{repo}/stargazers?per_page=100&page={page}", token)

    dates: list[dt.date] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, page_count)) as executor:
        pages = executor.map(fetch_page, range(1, page_count + 1))

    for items in pages:
        if not isinstance(items, list):
            raise RuntimeError("Unexpected response from GitHub's stargazers API")
        for item in items:
            dates.append(dt.datetime.fromisoformat(item["starred_at"].replace("Z", "+00:00")).date())
    return sorted(dates)


def nice_max(value: int) -> int:
    if value <= 10:
        return 10
    magnitude = 10 ** (len(str(value)) - 1)
    step = magnitude / 2
    return int(math.ceil(value / step) * step)


def render_svg(repo: str, dates: list[dt.date]) -> str:
    if not dates:
        raise RuntimeError("No star history was returned for this repository")

    width, height = 1200, 630
    left, right, top, bottom = 105, 55, 130, 90
    plot_width = width - left - right
    plot_height = height - top - bottom

    start = dates[0]
    end = max(dates[-1], dt.datetime.now(dt.timezone.utc).date())
    day_span = max((end - start).days, 1)
    daily = Counter(dates)
    series: list[tuple[dt.date, int]] = []
    total = 0
    for offset in range(day_span + 1):
        day = start + dt.timedelta(days=offset)
        total += daily[day]
        series.append((day, total))

    y_max = nice_max(total)

    def x(day: dt.date) -> float:
        return left + ((day - start).days / day_span) * plot_width

    def y(value: int) -> float:
        return top + plot_height - (value / y_max) * plot_height

    points = " ".join(f"{x(day):.1f},{y(value):.1f}" for day, value in series)
    area_points = f"{left},{top + plot_height} {points} {left + plot_width},{top + plot_height}"

    y_grid: list[str] = []
    for index in range(5):
        value = round(y_max * index / 4)
        ypos = y(value)
        label = f"{value / 1000:g}k" if value >= 1000 else str(value)
        y_grid.append(
            f'<line x1="{left}" y1="{ypos:.1f}" x2="{left + plot_width}" y2="{ypos:.1f}" '
            'stroke="#e5e7eb" stroke-width="1" />'
            f'<text x="{left - 18}" y="{ypos + 6:.1f}" text-anchor="end" class="axis">{label}</text>'
        )

    x_ticks: list[str] = []
    for index in range(5):
        day = start + dt.timedelta(days=round(day_span * index / 4))
        xpos = x(day)
        anchor = "start" if index == 0 else "end" if index == 4 else "middle"
        x_ticks.append(
            f'<text x="{xpos:.1f}" y="{top + plot_height + 40}" text-anchor="{anchor}" '
            f'class="axis">{day.strftime("%b %d")}</text>'
        )

    updated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    safe_repo = escape(repo)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Star history for {safe_repo}</title>
  <desc id="desc">{total} GitHub stars from {start.isoformat()} through {end.isoformat()}</desc>
  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#f97316" stop-opacity="0.30" />
      <stop offset="100%" stop-color="#f97316" stop-opacity="0.02" />
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="5" stdDeviation="10" flood-color="#0f172a" flood-opacity="0.08" />
    </filter>
  </defs>
  <style>
    .title {{ font: 700 34px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #111827; }}
    .subtitle {{ font: 500 17px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #6b7280; }}
    .axis {{ font: 500 15px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #6b7280; }}
    .count {{ font: 700 18px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #ea580c; }}
  </style>
  <rect width="{width}" height="{height}" rx="22" fill="#f8fafc" />
  <rect x="28" y="28" width="{width - 56}" height="{height - 56}" rx="18" fill="#ffffff" filter="url(#shadow)" />
  <text x="{left}" y="72" class="title">⭐ Star History</text>
  <text x="{left}" y="102" class="subtitle">{safe_repo}</text>
  <text x="{left + plot_width}" y="78" text-anchor="end" class="count">{total:,} stars</text>
  {''.join(y_grid)}
  <polygon points="{area_points}" fill="url(#area)" />
  <polyline points="{points}" fill="none" stroke="#f04b23" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{x(series[-1][0]):.1f}" cy="{y(total):.1f}" r="7" fill="#f04b23" stroke="#ffffff" stroke-width="4" />
  {''.join(x_ticks)}
  <text x="{left + plot_width}" y="{height - 35}" text-anchor="end" class="subtitle">Updated {updated} · GitHub API</text>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "kangarooking/cangjie-skill"))
    parser.add_argument("--output", type=Path, default=Path("assets/star-history.svg"))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN or GH_TOKEN before running this script")

    dates = fetch_star_dates(args.repo, token)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_svg(args.repo, dates), encoding="utf-8")
    print(f"Wrote {args.output} with {len(dates)} stars")


if __name__ == "__main__":
    main()
