"""Shared constants for the SJTU Tennis Toolkit."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Monitoring defaults
# ---------------------------------------------------------------------------
DEFAULT_CHECK_INTERVAL_SECONDS = 20
MIN_CHECK_INTERVAL_SECONDS = 10
SETUP_SCAN_SECONDS = 1

# ---------------------------------------------------------------------------
# Court hours
# ---------------------------------------------------------------------------
OPEN_HOUR = 7
CLOSE_HOUR = 22

# ---------------------------------------------------------------------------
# Date visibility
# ---------------------------------------------------------------------------
EIGHTH_DAY_RELEASE_HOUR = 12

# ---------------------------------------------------------------------------
# Browser version
# ---------------------------------------------------------------------------
USER_DATA_DIR = "browser_profile"
DEBUG_PAGE_LIST_SECONDS = 60

# ---------------------------------------------------------------------------
# Auto order (monitor)
# ---------------------------------------------------------------------------
#: The booking grid lags behind a rejected submit, so the same cell can look
#: "the only free one" again on the very next round. Wait this long before
#: submitting the same cell twice.
AUTO_ORDER_RETRY_COOLDOWN_SECONDS = 60

# ---------------------------------------------------------------------------
# Booking grid geometry
# ---------------------------------------------------------------------------
# The booking page can only be read through JS probes, and every probe used to
# carry its own copy of these numbers. They are collected here so a page
# redesign has exactly one place to describe: the probes read them from the
# ``geom`` argument of the call (see browser/js_snippets.py).
#
#: The booking grid always shows this many court columns.
TENNIS_COURT_COUNT = 8
#: Minimum number of date tabs the page must render before it counts as loaded.
DATE_TAB_READY_COUNT = 7

#: Pixel values handed to every probe as its ``geom`` argument.
BOOKING_GRID_GEOMETRY: dict[str, int] = {
    # Smallest box that counts as visible at all; the grid is full of 0x0
    # layout wrappers.
    "minVisiblePixels": 4,
    # Slack around the detected court columns / time rows when deciding whether
    # a box belongs to the grid at all.
    "paddingX": 20,
    "paddingTop": 20,
    "paddingBottom": 80,
    # A real grid cell is roughly this big; anything else is a label or a
    # wrapper around one.
    "cellMinWidth": 25,
    "cellMaxWidth": 90,
    "cellMinHeight": 20,
    "cellMaxHeight": 70,
    # How close a box has to sit to the target row / column centre to count as
    # "the cell for that hour and court".
    "maxRowDistance": 45,
    "maxColumnDistance": 60,
    # How far the cell probe walks up the DOM while looking for state markers,
    # and how big an ancestor may still be to count as the same cell.
    "cellParentDepth": 5,
    "cellProbeMaxWidth": 120,
    "cellProbeMaxHeight": 90,
    "cellProbeCenterTolerance": 8,
    # The monitor scanner uses a shallower walk: it starts at the cell itself
    # and climbs 3 parents.
    "scannerChainDepth": 4,
    # Light blue background = selectable.
    "selectableBlueMinBlue": 185,
    "selectableBlueMinGreen": 120,
    "selectableBlueMaxRed": 210,
    "selectableBlueMinBlueMinusRed": 30,
    "selectableBlueMinBlueMinusGreen": 8,
    # Green background = already selected in the order bar.
    "selectedGreenMinGreen": 130,
    "selectedGreenMaxRed": 120,
    "selectedGreenMaxBlue": 180,
    "selectedGreenMinGreenMinusRed": 45,
    # Grey background = taken or disabled.
    "greyMaxChannelDelta": 18,
    "greyMinRed": 115,
    "greyMaxRed": 245,
    # Court columns the grid has to expose before it counts as loaded.
    "courtCount": TENNIS_COURT_COUNT,
}
