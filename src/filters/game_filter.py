"""Game list filtering — 1G1R, region, search, clean-filter, letter.

All functions are pure: they accept list[GameFile] and return list[GameFile].
The UI is responsible for converting GameFile objects to display strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from src.core.constants import CLEAN_FILTER_KEYWORDS
from src.core.models import GameFile


# ---------------------------------------------------------------------------
# Filter configuration
# ---------------------------------------------------------------------------


@dataclass
class FilterConfig:
    search_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    try_to_clean: bool = False
    letter: str = "All"
    master_region: str = "All Regions"
    apply_1g1r: bool = False
    preferred_region: str = "USA"
    remove_alt_regions: bool = False
    hide_downloaded: bool = False
    downloaded: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply(games: list[GameFile], cfg: FilterConfig) -> list[GameFile]:
    """Return a filtered and sorted copy of *games* according to *cfg*."""
    result = games[:]

    result = _apply_search(result, cfg.search_keywords)
    result = _apply_exclude(result, cfg.exclude_keywords, cfg.try_to_clean)
    result = _apply_letter(result, cfg.letter)
    result = _apply_region(result, cfg.master_region, cfg.apply_1g1r)
    result = _apply_remove_alt_regions(result, cfg.master_region, cfg.apply_1g1r, cfg.remove_alt_regions)
    result = _apply_hide_downloaded(result, cfg.hide_downloaded, cfg.downloaded)

    if cfg.apply_1g1r:
        result = _apply_1g1r(result, cfg.preferred_region)

    return sorted(result, key=lambda g: g.filename.lower())


# ---------------------------------------------------------------------------
# Individual filter steps
# ---------------------------------------------------------------------------


def _apply_search(games: list[GameFile], keywords: list[str]) -> list[GameFile]:
    if not keywords:
        return games
    lower_kws = [k.lower() for k in keywords]
    return [g for g in games if any(kw in g.filename.lower() for kw in lower_kws)]


def _apply_exclude(
    games: list[GameFile],
    keywords: list[str],
    try_to_clean: bool,
) -> list[GameFile]:
    active = list(keywords)
    if try_to_clean:
        active.extend(CLEAN_FILTER_KEYWORDS)
    if not active:
        return games
    lower_kws = [k.lower() for k in active]
    return [g for g in games if not any(kw in g.filename.lower() for kw in lower_kws)]


def _apply_letter(games: list[GameFile], letter: str) -> list[GameFile]:
    if letter == "All":
        return games
    if letter == "#":
        return [g for g in games if g.filename and g.filename[0].isdigit()]
    return [g for g in games if g.filename.lower().startswith(letter.lower())]


def _apply_region(
    games: list[GameFile],
    master_region: str,
    apply_1g1r: bool,
) -> list[GameFile]:
    if master_region == "All Regions":
        return games

    region_lower = master_region.lower()

    if apply_1g1r:
        # Keep entries that match the master region; fall back to (World)
        by_base: dict[str, list[GameFile]] = {}
        for g in games:
            by_base.setdefault(_base_name(g.filename), []).append(g)

        result: list[GameFile] = []
        for versions in by_base.values():
            matches = [
                g for g in versions
                if _has_region(g.filename, region_lower)
            ]
            if matches:
                result.extend(matches)
            else:
                world = [g for g in versions if "(world)" in g.filename.lower()]
                result.extend(world)
        return result

    # Simple region tag filter
    tag = f"({master_region.lower()})"
    return [g for g in games if tag in g.filename.lower()]


def _apply_remove_alt_regions(
    games: list[GameFile],
    master_region: str,
    apply_1g1r: bool,
    remove_alt: bool,
) -> list[GameFile]:
    # remove_alt_regions is mutually exclusive with master_region filter
    if not remove_alt or master_region != "All Regions" or apply_1g1r:
        return games
    core = {"(usa)", "(europe)", "(japan)"}
    return [g for g in games if any(r in g.filename.lower() for r in core)]


def _apply_hide_downloaded(
    games: list[GameFile],
    hide: bool,
    downloaded: set[str],
) -> list[GameFile]:
    if not hide:
        return games
    return [g for g in games if g.filename not in downloaded]


# ---------------------------------------------------------------------------
# 1G1R
# ---------------------------------------------------------------------------


def _apply_1g1r(games: list[GameFile], preferred_region: str) -> list[GameFile]:
    by_base: dict[str, list[GameFile]] = {}
    for g in games:
        by_base.setdefault(_base_name(g.filename), []).append(g)

    result: list[GameFile] = []
    for versions in by_base.values():
        if len(versions) == 1:
            result.append(versions[0])
        else:
            # Pre-compute scores once — avoids O(n log n) repeated calls inside max()
            scored = [(g, _rom_score(g.filename, preferred_region)) for g in versions]
            result.append(max(scored, key=lambda t: t[1])[0])
    return result


# ---------------------------------------------------------------------------
# Scoring helpers for 1G1R algorithm
# ---------------------------------------------------------------------------


_REGION_SCORES: dict[str, int] = {"usa": 900, "world": 800, "europe": 700, "japan": 600}
_PRIORITY_ORDER: tuple[str, ...] = ("usa", "world", "europe", "japan")

_PENALTY_TAGS: tuple[str, ...] = (
    "(proto)", "(beta)", "[b]", "(demo)", "demo", "(sample)",
    "(unl)", "(virtual console)", "(kiosk)", "(anniversary collection)",
)

_REV_RE = re.compile(r"\(rev\s*(\d+)\)|\(v(\d\.\d)\)", re.IGNORECASE)
_REV_TAGS_RE = re.compile(r"\(rev\s*\d+\)|\(v\d+\.\d+\)", re.IGNORECASE)


@lru_cache(maxsize=2048)
def _rom_score(filename: str, preferred_region: str) -> float:
    lower = filename.lower()
    pref = preferred_region.lower()
    score = 0.0

    check_order = [pref] + [r for r in _PRIORITY_ORDER if r != pref]
    for region in check_order:
        if f"({region})" in lower:
            score += 1000 if region == pref else _REGION_SCORES.get(region, 0)
            break

    rev = _REV_RE.search(lower)
    if rev:
        score += int(rev.group(1)) * 10 if rev.group(1) else int(float(rev.group(2)) * 10)

    if "[!]" in lower:
        score += 50

    for tag in _PENALTY_TAGS:
        if tag in lower:
            score -= 10_000

    tag_count = lower.count("(")
    if tag_count > 1:
        # Exempt revision/version tags from the penalty so that (Rev 1) / (v1.0)
        # score correctly above an unversioned ROM (BUG-003 fix).
        revision_tags = _REV_TAGS_RE.findall(lower)
        penalizable = tag_count - len(revision_tags)
        if penalizable > 1:
            score -= (penalizable - 1) * 200

    score -= len(lower) / 10.0
    return score


_PART_RE = re.compile(
    r"\((disc|cd|disk|tape|side|part|vol\.?)[\s\-]*[0-9a-z]+(\s+of\s+[0-9]+)?\)",
    re.IGNORECASE,
)
_TAGS_RE = re.compile(r"\s*\(.*?\)\s*|\s*\[.*?\]\s*")
_FIRST_PAREN_RE = re.compile(r"\((.*?)\)")
_REGION_SPLIT_RE = re.compile(r"[,/&\s]+")


@lru_cache(maxsize=2048)
def _base_name(filename: str) -> str:
    part_match = _PART_RE.search(filename)
    part_suffix = f" - {part_match.group(0)[1:-1].strip()}" if part_match else ""
    base = _TAGS_RE.sub("", filename).strip()
    if len(base) < 4 and " - " in filename:
        base = filename.split(" - ")[0].strip()
    return (base or filename) + part_suffix


@lru_cache(maxsize=2048)
def _has_region(filename: str, region_lower: str) -> bool:
    match = _FIRST_PAREN_RE.search(filename)
    if not match:
        return False
    regions = [r.strip().lower() for r in _REGION_SPLIT_RE.split(match.group(1))]
    return region_lower in regions
