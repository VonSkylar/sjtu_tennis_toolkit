"""Data models for the SJTU Tennis Toolkit."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sjtu_tennis_toolkit.constants import BOOKING_RULES, EIGHTH_DAY_RELEASE_HOUR


@dataclass(frozen=True)
class Venue:
    key: str
    name: str
    url: str


def _venue_url(key: str, venue_id: str) -> str:
    locale = "?locale=zh" if key == "huxiaoming" else ""
    return (
        f'{BOOKING_RULES["schoolOrigin"]}/pc/{locale}'
        f"#/apointmentDetails/1/{venue_id}/%25E5%2585%25A8%25E9%2583%25A8/0"
    )


VENUES = tuple(
    Venue(key=key, name=venue["name"], url=_venue_url(key, venue["id"]))
    for key, venue in BOOKING_RULES["venues"].items()
)
VENUES_BY_KEY = {venue.key: venue for venue in VENUES}


@dataclass(frozen=True)
class MonitorConfig:
    venues: tuple[Venue, ...]
    dates: tuple[dt.date, ...]
    start_hour: int
    end_hour: int
    check_interval_seconds: int
    auto_order_enabled: bool
    huxiaoming_court_scope: str = "all"


@dataclass(frozen=True)
class RushTimeSlot:
    start_hour: int
    end_hour: int


@dataclass(frozen=True)
class RushConfig:
    venue: Venue
    target_date: dt.date
    time_slots: tuple[RushTimeSlot, ...]
    preferred_court: int
    release_time: dt.time = dt.time(hour=EIGHTH_DAY_RELEASE_HOUR)
    huxiaoming_court_scope: str = "all"


@dataclass(frozen=True)
class Slot:
    venue_key: str
    venue: str
    date: dt.date
    court: str
    hour: str
