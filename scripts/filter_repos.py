#!/usr/bin/env python3
"""Filter RepoRecon KiCad index into acquisition candidates.

Reads reporecon_index.json, applies quality filters, and outputs
candidates.json sorted by stars descending.

Usage:
    python3 scripts/filter_repos.py [--min-stars N] [--max-age-years N] [--report]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
INDEX_PATH = DATA_DIR / "reporecon_index.json"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
RAW_DIR = DATA_DIR / "raw"


def load_index(path: Path) -> list[dict]:
    """Load the RepoRecon JSON index."""
    with open(path) as f:
        return json.load(f)


def existing_repos(raw_dir: Path) -> set[str]:
    """Return set of 'owner__repo' directory names already in data/raw/."""
    if not raw_dir.is_dir():
        return set()
    return {d.name for d in raw_dir.iterdir() if d.is_dir()}


def repo_dir_name(owner: str, repo: str) -> str:
    """Convert owner/repo to filesystem directory name."""
    return f"{owner}__{repo}"


def filter_repos(
    repos: list[dict],
    min_stars: int = 3,
    max_age_years: int = 3,
    skip_existing: set[str] | None = None,
) -> list[dict]:
    """Apply quality filters to the repo list.

    Filters:
        1. Stars >= min_stars
        2. Pushed within max_age_years
        3. Skip repos already in data/raw/

    Returns filtered list sorted by stars descending.
    """
    if skip_existing is None:
        skip_existing = set()

    cutoff = datetime.now(timezone.utc).replace(
        year=datetime.now(timezone.utc).year - max_age_years
    )
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    candidates = []
    for r in repos:
        # Filter 1: minimum stars
        if r.get("stars", 0) < min_stars:
            continue

        # Filter 2: pushed recently enough
        pushed = r.get("pushed", "")
        if pushed and pushed < cutoff_str:
            continue

        # Filter 3: skip existing
        dir_name = repo_dir_name(r.get("owner", ""), r.get("repo", ""))
        if dir_name in skip_existing:
            continue

        candidates.append({
            "full_name": f"{r['owner']}/{r['repo']}",
            "html_url": r.get("url", ""),
            "stars": r.get("stars", 0),
            "pushed_at": pushed,
            "description": r.get("description", ""),
            "forks": r.get("forks", 0),
            "size_kb": r.get("size", 0),
        })

    # Sort by stars descending
    candidates.sort(key=lambda c: c["stars"], reverse=True)
    return candidates


def print_report(candidates: list[dict], total_raw: int):
    """Print summary statistics about the filtered candidates."""
    print(f"\n{'='*60}")
    print("RepoRecon KiCad Filter Report")
    print(f"{'='*60}")
    print(f"Total repos in index:     {total_raw:,}")
    print(f"Candidates after filter:  {len(candidates):,}")
    print()

    if not candidates:
        print("No candidates found.")
        return

    stars = [c["stars"] for c in candidates]
    print(f"Stars range: {min(stars)} - {max(stars)}")
    print()

    # Star distribution buckets
    buckets = [
        (3, 9),
        (10, 49),
        (50, 99),
        (100, 499),
        (500, 999),
        (1000, float("inf")),
    ]
    print("Star distribution:")
    for lo, hi in buckets:
        count = sum(1 for s in stars if lo <= s <= hi)
        hi_label = f"{int(hi)}" if hi != float("inf") else "+"
        label = f"  {lo}-{hi_label}".ljust(14)
        bar = "#" * min(count // 5, 40)
        print(f"{label} {count:5,}  {bar}")
    print()

    # Top 20
    print("Top 20 by stars:")
    for c in candidates[:20]:
        desc = (c["description"] or "")[:50]
        print(f"  {c['stars']:5,}  {c['full_name']:<45s}  {desc}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Filter RepoRecon KiCad repos")
    parser.add_argument(
        "--min-stars", type=int, default=3, help="Minimum star count (default: 3)"
    )
    parser.add_argument(
        "--max-age-years",
        type=int,
        default=3,
        help="Max years since last push (default: 3)",
    )
    parser.add_argument(
        "--report", action="store_true", help="Print summary report"
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=INDEX_PATH,
        help="Path to reporecon_index.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=CANDIDATES_PATH,
        help="Path to output candidates.json",
    )
    args = parser.parse_args()

    if not args.index.exists():
        print(f"Error: Index file not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    repos = load_index(args.index)
    skip = existing_repos(RAW_DIR)

    candidates = filter_repos(
        repos,
        min_stars=args.min_stars,
        max_age_years=args.max_age_years,
        skip_existing=skip,
    )

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(candidates, f, indent=2)
    print(f"Wrote {len(candidates)} candidates to {args.output}")

    if args.report:
        print_report(candidates, len(repos))


if __name__ == "__main__":
    main()
