"""Shared booking-page primitives used by both the monitor and the rush booker.

The booking page can only be driven through JS probes plus coordinate clicks.
VenueMonitor (auto order) and RushBooker (timed rush) need exactly the same
probes, so they live here instead of being copied into each class.

A host class mixing this in must provide:

    self.events      -- queue.Queue receiving ("log", message) tuples
    self.stop_event  -- threading.Event that aborts every waiting loop
"""

from __future__ import annotations

import time

from sjtu_tennis_toolkit.browser.js_snippets import grid_arguments, grid_probe
from sjtu_tennis_toolkit.models import Slot


def point_inside_viewport(x: float, y: float, width: float, height: float, margin: float = 4.0) -> bool:
    return margin <= x <= width - margin and margin <= y <= height - margin


def slot_cell_can_submit(state: str) -> bool:
    return state in {"available", "selected"}


def slot_cell_needs_click(state: str, selected_order_matches: bool = False) -> bool:
    if state == "available":
        return True
    if state == "selected":
        return not selected_order_matches
    return False


class BookingPageActions:
    """JS probes and click helpers shared by every booking-page driver."""

    #: Repeated "still waiting" logs closer together than this are dropped.
    ATTEMPT_LOG_INTERVAL_SECONDS = 0.8

    def __init__(self) -> None:
        self._last_attempt_log_at = 0.0

    # ------------------------------------------------------------------
    # Grid cells
    # ------------------------------------------------------------------
    def _slot_cell_state(self, page, slot: Slot) -> dict[str, object]:
        return page.evaluate(
            grid_probe("targetCourt, targetHour", """
              const all = visibleElements();

              const timeNodes = all
                .map((el) => ({ el, text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^\\d{2}:00$/.test(item.text))
                .sort((a, b) => a.rect.top - b.rect.top);
              const courtNodes = all
                .map((el) => ({ el, text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^场地\\d+$/.test(item.text))
                .sort((a, b) => a.rect.left - b.rect.left);

              const targetTime = timeNodes.find((item) => item.text === targetHour);
              const targetCourtNode = courtNodes.find((item) => item.text === targetCourt);
              if (!targetTime || !targetCourtNode) {
                return { state: 'loading', reason: '目标时间行或场地列还没加载出来' };
              }

              const bounds = gridBounds(courtNodes, timeNodes);
              const targetX = targetCourtNode.rect.left + targetCourtNode.rect.width / 2;
              const targetY = targetTime.rect.top + targetTime.rect.height / 2;

              const rgbValues = (text) => {
                const values = [];
                const pattern = /rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/g;
                let match;
                while ((match = pattern.exec(text.toLowerCase())) !== null) {
                  values.push([Number(match[1]), Number(match[2]), Number(match[3])]);
                }
                return values;
              };

              const hexValues = (text) => {
                const values = [];
                const pattern = /#([0-9a-f]{6})/gi;
                let match;
                while ((match = pattern.exec(text.toLowerCase())) !== null) {
                  const value = match[1];
                  values.push([
                    Number.parseInt(value.slice(0, 2), 16),
                    Number.parseInt(value.slice(2, 4), 16),
                    Number.parseInt(value.slice(4, 6), 16),
                  ]);
                }
                return values;
              };

              const localAncestors = (el, baseRect) => {
                const nodes = [el, ...Array.from(el.querySelectorAll('*'))];
                let current = el.parentElement;
                for (let depth = 0; current && depth < geom.cellParentDepth; depth += 1) {
                  const rect = current.getBoundingClientRect();
                  const centerX = rect.left + rect.width / 2;
                  const centerY = rect.top + rect.height / 2;
                  const baseCenterX = baseRect.left + baseRect.width / 2;
                  const baseCenterY = baseRect.top + baseRect.height / 2;
                  const sameCellArea =
                    rect.width <= geom.cellProbeMaxWidth &&
                    rect.height <= geom.cellProbeMaxHeight &&
                    Math.abs(centerX - baseCenterX) <= geom.cellProbeCenterTolerance &&
                    Math.abs(centerY - baseCenterY) <= geom.cellProbeCenterTolerance;
                  if (!sameCellArea) {
                    break;
                  }
                  nodes.push(current);
                  current = current.parentElement;
                }
                return nodes;
              };

              const classify = (el) => {
                const baseRect = el.getBoundingClientRect();
                const related = localAncestors(el, baseRect);

                const combined = related.map((node) => {
                  const text = norm(node.innerText || node.textContent || '');
                  const title = norm(node.getAttribute('title'));
                  const aria = norm(node.getAttribute('aria-label'));
                  const ariaChecked = norm(node.getAttribute('aria-checked'));
                  const klass = norm(node.className && node.className.toString());
                  const dataState = norm(node.getAttribute('data-state') || node.getAttribute('data-status'));
                  return `${text}|${title}|${aria}|${ariaChecked}|${klass}|${dataState}`;
                }).join('|');

                const colorText = related.map((node) => {
                  const style = window.getComputedStyle(node);
                  return [
                    style.backgroundColor,
                    style.borderColor,
                    style.color,
                    style.fill,
                    style.stroke,
                    style.backgroundImage,
                    node.getAttribute('fill') || '',
                    node.getAttribute('stroke') || '',
                    node.getAttribute('style') || '',
                  ].join(' ');
                }).join(' ');

                const decodedColorText = (() => {
                  try {
                    return decodeURIComponent(colorText);
                  } catch {
                    return colorText;
                  }
                })();
                const colors = [...rgbValues(decodedColorText), ...hexValues(decodedColorText)];
                const hasGreen = colors.some(([r, g, b]) => isSelectedGreen(r, g, b));
                if (/selected|active|checked|is-checked/i.test(combined) || hasGreen) {
                  return { state: 'selected', reason: '格子已选中' };
                }

                const hasBlue = colors.some(([r, g, b]) => isSelectableBlue(r, g, b));
                if (/available|selectable|free|empty|enabled|optional|appointable/i.test(combined) || hasBlue) {
                  return { state: 'available', reason: '蓝色可选格子' };
                }

                if (/不可选|已约|已满|禁用|disabled|disable|unavailable|booked|sold|reserved/i.test(combined)) {
                  return { state: 'unavailable', reason: '格子标记为不可选' };
                }

                const hasGray = colors.some(([r, g, b]) => isUnavailableGrey(r, g, b));
                if (hasGray) {
                  return { state: 'unavailable', reason: '灰色不可选格子' };
                }

                return { state: 'unknown', reason: '无法识别格子颜色状态' };
              };

              const candidates = all
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .filter((item) => boxInsideGrid(item.rect, bounds) && boxIsGridCell(item.rect))
                .map((item) => ({
                  ...item,
                  centerX: item.rect.left + item.rect.width / 2,
                  centerY: item.rect.top + item.rect.height / 2,
                }))
                .filter((item) =>
                  columnDistance(item.rect, targetX) <= geom.maxColumnDistance &&
                  rowDistance(item.rect, targetY) <= geom.maxRowDistance
                );
              candidates.sort((a, b) => {
                const aDistance = Math.abs(a.centerX - targetX) + Math.abs(a.centerY - targetY);
                const bDistance = Math.abs(b.centerX - targetX) + Math.abs(b.centerY - targetY);
                if (Math.abs(aDistance - bDistance) > 1) {
                  return aDistance - bDistance;
                }
                return (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height);
              });

              const best = candidates[0];
              if (!best) {
                return { state: 'not_found', reason: '没有找到目标格子' };
              }

              const classification = classify(best.el);
              return {
                state: classification.state,
                reason: classification.reason,
                x: best.centerX,
                y: best.centerY,
              };
            }
            """),
            grid_arguments(targetCourt=slot.court, targetHour=slot.hour),
        )

    def _scroll_slot_into_view(self, page, slot: Slot) -> None:
        result = page.evaluate(
            grid_probe("targetHour", """
              const timeNode = visibleElements()
                .map((el) => ({ el, text: norm(el.innerText || el.textContent || '') }))
                .find((item) => item.text === targetHour);
              if (!timeNode) {
                return { error: `没有找到 ${targetHour} 时间行，不能滚动到目标位置` };
              }
              timeNode.el.scrollIntoView({ block: 'center', inline: 'nearest' });
              return { ok: true };
            }
            """),
            grid_arguments(targetHour=slot.hour),
        )
        if result.get("error"):
            raise RuntimeError(result["error"])
        page.wait_for_timeout(80)

    def _try_select_slot_cell(self, page, slot: Slot, cell_state: dict[str, object]) -> None:
        x = cell_state.get("x")
        y = cell_state.get("y")
        if x is None or y is None:
            raise RuntimeError(f"没有 {slot.court} {slot.hour} 的点击坐标")
        x = float(x)
        y = float(y)
        if not self._is_click_point_in_viewport(page, x, y):
            self._scroll_slot_into_view(page, slot)
            refreshed_state = self._slot_cell_state(page, slot)
            refreshed_state_name = str(refreshed_state.get("state", ""))
            if not slot_cell_can_submit(refreshed_state_name):
                raise RuntimeError(f"滚动后 {slot.court} {slot.hour} 已不可下单：{refreshed_state.get('reason')}")
            x = refreshed_state.get("x")
            y = refreshed_state.get("y")
            if x is None or y is None:
                raise RuntimeError(f"滚动后仍没有 {slot.court} {slot.hour} 的点击坐标")
            x = float(x)
            y = float(y)
            if not self._is_click_point_in_viewport(page, x, y):
                raise RuntimeError(f"{slot.court} {slot.hour} 不在当前可点击范围内")
        page.mouse.click(x, y)
        page.wait_for_timeout(120)

    def _is_click_point_in_viewport(self, page, x: float, y: float) -> bool:
        viewport = page.evaluate(
            """
            () => ({ width: window.innerWidth, height: window.innerHeight })
            """
        )
        return point_inside_viewport(x, y, float(viewport["width"]), float(viewport["height"]))

    def _wait_for_slot_selected(self, page, slot: Slot) -> bool:
        end_at = time.monotonic() + 1.2
        while time.monotonic() < end_at and not self.stop_event.is_set():
            if self._selected_order_matches_slot(page, slot):
                return True
            if self._failure_notice_text(page):
                return False
            page.wait_for_timeout(100)
        return False

    def _selected_order_matches_slot(self, page, slot: Slot) -> bool:
        try:
            body_text = page.evaluate(
                """
                () => (document.body.innerText || document.body.textContent || '')
                """
            )
        except Exception:
            return False
        compact = "".join(str(body_text or "").split())
        try:
            end_hour = int(slot.hour.split(":", 1)[0]) + 1
        except ValueError:
            end_hour = 0
        time_range = f"{slot.hour}-{end_hour:02d}:00" if end_hour else slot.hour
        return slot.court in compact and time_range in compact

    # ------------------------------------------------------------------
    # Buttons and notices
    # ------------------------------------------------------------------
    def _click_visible_text_button(self, page, text: str, timeout: int) -> None:
        end_at = time.monotonic() + timeout / 1000
        last_error = ""
        while time.monotonic() < end_at and not self.stop_event.is_set():
            result = page.evaluate(
                grid_probe("text", """
                  const targetText = norm(text);
                  const candidates = Array.from(document.querySelectorAll('button,[role="button"],.el-button,.ant-btn'))
                    .filter(visible)
                    .filter((el) => norm(el.innerText || el.textContent || '').includes(targetText))
                    .filter((el) => !el.disabled && !/disabled|is-disabled/.test(String(el.className || '')));
                  const target = candidates[candidates.length - 1];
                  if (!target) {
                    return { error: `没有找到可见按钮：${text}` };
                  }
                  target.scrollIntoView({ block: 'center', inline: 'center' });
                  const rect = target.getBoundingClientRect();
                  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
                }
                """),
                grid_arguments(text=text),
            )
            if not result.get("error"):
                page.mouse.click(result["x"], result["y"])
                return
            last_error = result["error"]
            page.wait_for_timeout(100)
        raise RuntimeError(last_error or f"没有找到可见按钮：{text}")

    def _accept_booking_notice_fast(self, page) -> bool:
        end_at = time.monotonic() + 2.0
        while time.monotonic() < end_at and not self.stop_event.is_set():
            result = page.evaluate(
                grid_probe("", """
                  const bodyText = norm(document.body.innerText);
                  if (!/预订须知|本人已认真阅读|自愿接受|同意/.test(bodyText)) {
                    return { ok: false, reason: '预订须知弹窗还没出现' };
                  }

                  const checkedByClass = Array.from(document.querySelectorAll('.is-checked,.el-checkbox__input.is-checked,[aria-checked="true"]'))
                    .some(visible);
                  const checkedInput = Array.from(document.querySelectorAll('input[type="checkbox"]'))
                    .some((input) => input.checked);
                  if (checkedByClass || checkedInput) {
                    return { ok: true, reason: '须知已勾选' };
                  }

                  const labels = Array.from(document.querySelectorAll('label')).filter(visible);
                  const label = labels.find((item) => /本人已认真阅读|自愿接受|同意/.test(norm(item.innerText)));
                  if (label) {
                    label.click();
                    return { ok: false, reason: '已点击须知文字，等待勾选生效' };
                  }

                  const checkbox = Array.from(document.querySelectorAll('input[type="checkbox"]')).find((item) => !item.checked);
                  if (checkbox) {
                    checkbox.click();
                    return { ok: false, reason: '已点击复选框，等待勾选生效' };
                  }

                  const box = Array.from(document.querySelectorAll('.el-checkbox,.el-checkbox__input,.ant-checkbox,.ant-checkbox-wrapper'))
                    .find(visible);
                  if (box) {
                    box.click();
                    return { ok: false, reason: '已点击复选框区域，等待勾选生效' };
                  }

                  return { ok: false, reason: '没有找到须知勾选框' };
                }
                """),
                grid_arguments(),
            )
            if result.get("ok"):
                return True
            self._log_attempt_wait(str(result.get("reason", "正在勾选预订须知")))
            page.wait_for_timeout(100)

        return False

    def _wait_for_order_result(self, page, timeout_seconds: float = 3.0) -> tuple[str, str]:
        """Read back the order outcome. Never assume success from "no exception"."""
        end_at = time.monotonic() + timeout_seconds
        while time.monotonic() < end_at and not self.stop_event.is_set():
            failure = self._failure_notice_text(page)
            if failure:
                return "failure", failure
            success = self._success_notice_text(page)
            if success:
                return "success", success
            page.wait_for_timeout(120)
        return "unknown", "提交后没有看到明确成功或失败提示"

    def _notice_text(self, page) -> str:
        text = page.evaluate(
            grid_probe("", """
              const selectors = [
                '.el-message',
                '.ant-message',
                '.van-toast',
                '.toast',
                '[role="alert"]',
                '.message',
                '.notice'
              ];
              const nodes = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)));
              const texts = nodes.filter(visible).map((node) => node.innerText || node.textContent || '');
              return texts.join('\\n');
            }
            """),
            grid_arguments(),
        )
        return "".join(str(text or "").split())

    def _success_notice_text(self, page) -> str:
        compact = self._notice_text(page)
        if not compact:
            return ""
        success_patterns = (
            "预约成功",
            "预订成功",
            "下单成功",
            "提交成功",
            "订单提交成功",
        )
        for pattern in success_patterns:
            if pattern in compact:
                return compact
        return ""

    def _failure_notice_text(self, page) -> str:
        compact = self._notice_text(page)
        if not compact:
            return ""
        failure_patterns = (
            "已被预定",
            "请重新选择时段",
            "预约失败",
            "下单失败",
            "提交失败",
            "无法预约",
            "已被预约",
            "库存不足",
            "请选择场地",
            "请先选择场地",
        )
        for pattern in failure_patterns:
            if pattern in compact:
                return compact
        return ""

    def _clear_transient_notices(self, page) -> None:
        try:
            page.evaluate(
                """
                () => {
                  const selectors = [
                    '.el-message',
                    '.ant-message',
                    '.van-toast',
                    '.toast',
                    '[role="alert"]'
                  ];
                  for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                      node.remove();
                    }
                  }
                }
                """
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _log_attempt_wait(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_attempt_log_at >= self.ATTEMPT_LOG_INTERVAL_SECONDS:
            self._last_attempt_log_at = now
            self.events.put(("log", message))
