"""Last-used settings persistence for the rush booking GUI.

Only the fields the user actually picks are remembered: venue, court scope,
preferred court, release time and the ordered list of time ranges. The target
date is always recomputed on start-up, so it is deliberately never stored.

Every value is validated on load and silently falls back to the shipped default
when it is missing, corrupt or out of range - a damaged state file must never
stop the tool from starting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sjtu_tennis_toolkit.config import (
    DEFAULT_RUSH_HUXIAOMING_COURT_SCOPE,
    DEFAULT_RUSH_PREFERRED_COURT,
    DEFAULT_RUSH_TIME_RANGES,
    DEFAULT_RUSH_VENUE_KEY,
    HUXIAOMING_COURT_SCOPE_ALL,
    HUXIAOMING_COURT_SCOPE_LABELS,
    MAX_RUSH_TIME_SLOTS,
    parse_huxiaoming_court_scope,
    parse_rush_start_time,
    rush_allowed_courts,
    rush_time_options,
)
from sjtu_tennis_toolkit.models import VENUES_BY_KEY


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
# Written next to the project root, same as ``rate_limit_until.txt``. The
# launcher batch scripts ``cd`` into the project directory before starting.
RUSH_STATE_FILE = Path("rush_state.json")
RUSH_STATE_VERSION = 1
DEFAULT_RUSH_RELEASE_TIME_TEXT = "12:00:00"


@dataclass(frozen=True)
class RushUiState:
    """The subset of rush settings that is remembered between runs."""

    venue_key: str
    huxiaoming_court_scope: str
    court: int
    release_time_text: str
    time_range_texts: tuple[str, ...]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def normalize_rush_ui_state(
    venue_key: object = None,
    huxiaoming_court_scope: object = None,
    court_text: object = None,
    release_time_text: object = None,
    time_range_texts: object = None,
) -> RushUiState:
    """Coerce arbitrary input into a valid state, falling back field by field."""
    normalized_venue = _normalize_venue_key(venue_key)
    if normalized_venue == "huxiaoming":
        scope = _normalize_scope(huxiaoming_court_scope)
    else:
        # The scope selector only applies to 胡晓明网球场 and is disabled elsewhere.
        scope = HUXIAOMING_COURT_SCOPE_ALL

    allowed_courts = rush_allowed_courts(normalized_venue, scope)
    return RushUiState(
        venue_key=normalized_venue,
        huxiaoming_court_scope=scope,
        court=_normalize_court(court_text, allowed_courts),
        release_time_text=_normalize_release_time(release_time_text),
        time_range_texts=_normalize_time_ranges(time_range_texts),
    )


def _normalize_venue_key(value: object) -> str:
    if isinstance(value, str) and value.strip() in VENUES_BY_KEY:
        return value.strip()
    return DEFAULT_RUSH_VENUE_KEY


def _normalize_scope(value: object) -> str:
    if isinstance(value, str):
        try:
            return parse_huxiaoming_court_scope(value)
        except ValueError:
            pass
    return DEFAULT_RUSH_HUXIAOMING_COURT_SCOPE


def _normalize_court(value: object, allowed_courts: tuple[int, ...]) -> int:
    court: int | None = None
    if isinstance(value, bool):
        court = None
    elif isinstance(value, int):
        court = value
    elif isinstance(value, str):
        digits = value.strip().removeprefix("场地").strip()
        if digits.isdigit():
            court = int(digits)

    if court in allowed_courts:
        return court
    if DEFAULT_RUSH_PREFERRED_COURT in allowed_courts:
        return DEFAULT_RUSH_PREFERRED_COURT
    return allowed_courts[0]


def _normalize_release_time(value: object) -> str:
    if isinstance(value, str):
        try:
            return parse_rush_start_time(value).strftime("%H:%M:%S")
        except ValueError:
            pass
    return DEFAULT_RUSH_RELEASE_TIME_TEXT


def _normalize_time_ranges(value: object) -> tuple[str, ...]:
    options = set(rush_time_options())
    selected: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text in options and text not in selected:
                selected.append(text)
            if len(selected) >= MAX_RUSH_TIME_SLOTS:
                break
    if not selected:
        return DEFAULT_RUSH_TIME_RANGES
    return tuple(selected)


def describe_rush_ui_state(state: RushUiState) -> str:
    """Human readable one-line summary used in the log pane."""
    venue = VENUES_BY_KEY[state.venue_key].name
    scope = ""
    if state.venue_key == "huxiaoming":
        scope = f"（{HUXIAOMING_COURT_SCOPE_LABELS[state.huxiaoming_court_scope]}）"
    times = "、".join(state.time_range_texts)
    return f"{venue}{scope} 场地{state.court}，{times}，{state.release_time_text} 开始抢场"


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------
def load_rush_ui_state(path: str | Path | None = None) -> RushUiState:
    """Load the last-used settings; missing or corrupt files yield defaults."""
    target = Path(path) if path is not None else RUSH_STATE_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return normalize_rush_ui_state()
    if not isinstance(raw, dict):
        return normalize_rush_ui_state()
    return normalize_rush_ui_state(
        raw.get("venue_key"),
        raw.get("huxiaoming_court_scope"),
        raw.get("court"),
        raw.get("release_time"),
        raw.get("time_ranges"),
    )


def save_rush_ui_state(
    venue_key: object = None,
    huxiaoming_court_scope: object = None,
    court_text: object = None,
    release_time_text: object = None,
    time_range_texts: object = None,
    path: str | Path | None = None,
) -> RushUiState:
    """Persist the current settings. Invalid values are normalized first.

    Write failures are swallowed on purpose: setting a reminder for a file
    permission problem is not worth blocking the window from closing.
    """
    state = normalize_rush_ui_state(
        venue_key,
        huxiaoming_court_scope,
        court_text,
        release_time_text,
        time_range_texts,
    )
    payload = {
        "version": RUSH_STATE_VERSION,
        "venue_key": state.venue_key,
        "huxiaoming_court_scope": state.huxiaoming_court_scope,
        "court": state.court,
        "release_time": state.release_time_text,
        "time_ranges": list(state.time_range_texts),
    }
    target = Path(path) if path is not None else RUSH_STATE_FILE
    try:
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return state
