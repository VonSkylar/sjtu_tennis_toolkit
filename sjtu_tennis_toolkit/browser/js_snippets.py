"""Shared JavaScript fragments for the booking-page probes.

The booking page can only be inspected through ``page.evaluate``, and every
probe used to carry its own copy of ``visible()`` / ``norm()`` plus its own
copy of the grid geometry numbers. That meant a page tweak required editing
eight places and silently missing one of them.

Two things are deliberately *not* merged:

* the monitor asks "is this cell worth reporting?" (``isAvailable``), while the
  booking probe asks "can this cell be clicked and submitted?" (``classify``).
  Same page, different questions -- so the two predicates stay separate.
* the colour scrapers stay local too: the booking probe reads five style
  properties plus hex literals, the monitor reads three. Only the *threshold*
  is shared, as ``isSelectableBlue`` and friends.

The numbers are not baked into the strings. They arrive as the ``geom``
argument of the probe, built by :func:`grid_arguments` from
:data:`sjtu_tennis_toolkit.constants.BOOKING_GRID_GEOMETRY`, which keeps them
readable from Python and checkable without a browser.
"""

from __future__ import annotations

from sjtu_tennis_toolkit.constants import BOOKING_GRID_GEOMETRY

#: Name of the probe argument that carries ``BOOKING_GRID_GEOMETRY``.
GEOMETRY_ARGUMENT = "geom"

#: Prepended to the body of a probe by :func:`grid_probe`.
#:
#: These are statements inside the probe function, not an expression hoisted
#: next to it, on purpose: every ``page.evaluate`` runs in the page's global
#: scope, so a top-level ``const visible = ...`` would survive into the next
#: call and fail with "has already been declared".
GRID_HELPERS = """
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return (
      rect.width > geom.minVisiblePixels &&
      rect.height > geom.minVisiblePixels &&
      style.visibility !== 'hidden' &&
      style.display !== 'none'
    );
  };
  const norm = (text) => (text || '').replace(/\\s+/g, '').trim();
  const visibleElements = () => Array.from(document.querySelectorAll('body *')).filter(visible);
  const boxIsGridCell = (rect) =>
    rect.width >= geom.cellMinWidth &&
    rect.width <= geom.cellMaxWidth &&
    rect.height >= geom.cellMinHeight &&
    rect.height <= geom.cellMaxHeight;
  const gridBounds = (courtNodes, timeNodes) => ({
    left: Math.min(...courtNodes.map((item) => item.rect.left)) - geom.paddingX,
    right: Math.max(...courtNodes.map((item) => item.rect.right)) + geom.paddingX,
    top: Math.min(...timeNodes.map((item) => item.rect.top)) - geom.paddingTop,
    bottom: Math.max(...timeNodes.map((item) => item.rect.bottom)) + geom.paddingBottom,
  });
  const boxInsideGrid = (rect, bounds) =>
    rect.left >= bounds.left &&
    rect.right <= bounds.right &&
    rect.top >= bounds.top &&
    rect.bottom <= bounds.bottom;
  const rowDistance = (rect, y) => Math.abs(rect.top + rect.height / 2 - y);
  const columnDistance = (rect, x) => Math.abs(rect.left + rect.width / 2 - x);
  const isSelectableBlue = (r, g, b) =>
    b >= geom.selectableBlueMinBlue &&
    g >= geom.selectableBlueMinGreen &&
    r <= geom.selectableBlueMaxRed &&
    b - r >= geom.selectableBlueMinBlueMinusRed &&
    b - g >= geom.selectableBlueMinBlueMinusGreen;
  const isSelectedGreen = (r, g, b) =>
    g >= geom.selectedGreenMinGreen &&
    r <= geom.selectedGreenMaxRed &&
    b <= geom.selectedGreenMaxBlue &&
    g - r >= geom.selectedGreenMinGreenMinusRed;
  const isUnavailableGrey = (r, g, b) =>
    Math.abs(r - g) <= geom.greyMaxChannelDelta &&
    Math.abs(g - b) <= geom.greyMaxChannelDelta &&
    r >= geom.greyMinRed &&
    r <= geom.greyMaxRed;
"""


def grid_probe(params: str, body: str) -> str:
    """Wrap a probe ``body`` in the shared grid helpers.

    ``params`` lists the destructured probe arguments *without* the geometry
    object, which is always appended (pass ``""`` for a probe that takes no
    arguments). ``body`` is the remainder of the arrow function: it starts
    after the opening brace and ends with the closing brace.
    """
    arguments = ", ".join(part for part in (params, GEOMETRY_ARGUMENT) if part)
    return "({ " + arguments + " }) => {\n" + GRID_HELPERS + body


def grid_arguments(**values: object) -> dict[str, object]:
    """Build the ``evaluate`` argument object for a :func:`grid_probe` probe."""
    return {**values, GEOMETRY_ARGUMENT: BOOKING_GRID_GEOMETRY}
