"""RushBooker - timed browser-based booking at the configured release time."""

from __future__ import annotations

import datetime as dt
import queue
import threading
import time

from sjtu_tennis_toolkit.browser.booking_actions import (
    slot_cell_can_submit,
    slot_cell_needs_click,
)
from sjtu_tennis_toolkit.browser.js_snippets import grid_arguments, grid_probe
from sjtu_tennis_toolkit.browser.monitor import VenueMonitor
from sjtu_tennis_toolkit.config import (
    is_rush_start_allowed,
    rush_allowed_courts,
    rush_config_label,
    rush_court_attempt_order,
    rush_deadline_datetime,
    rush_release_datetime,
    target_date_labels,
)
from sjtu_tennis_toolkit.constants import DATE_TAB_READY_COUNT, USER_DATA_DIR
from sjtu_tennis_toolkit.exceptions import BookingPageNotReady, RequestRateLimited
from sjtu_tennis_toolkit.models import RushConfig, RushTimeSlot, Slot


def date_bar_ready(date_count: int) -> bool:
    return date_count >= DATE_TAB_READY_COUNT


def date_bar_action(date_bar_ready: bool, target_found: bool) -> str:
    if not date_bar_ready:
        return "wait"
    if not target_found:
        return "reload"
    return "select"


class RushBooker(VenueMonitor):
    """Open the booking page early, then make a timed single-slot order."""

    def __init__(self, config_provider, events: queue.Queue) -> None:
        super().__init__(config_provider, events)
        self._last_ready_log_at = 0.0
        self._user_stop_requested = False
        self._close_browser_event = threading.Event()

    def stop(self) -> None:
        self._user_stop_requested = True
        self._signal_close_browser()
        super().stop()

    def run(self) -> None:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.events.put(("error", "缺少 Playwright。请先运行：pip install -r requirements.txt，然后运行：python -m playwright install chromium"))
            return

        try:
            config = self.config_provider()
        except Exception as exc:
            self.events.put(("error", f"抢场条件有误：{exc}"))
            self.events.put(("stopped", "抢场已停止。"))
            return

        if not is_rush_start_allowed(release_time=config.release_time):
            deadline = rush_deadline_datetime(release_time=config.release_time)
            self.events.put(("failed", f"抢场时间已过。本次抢场截止时间为 {deadline.strftime('%H:%M:%S')}。"))
            self.events.put(("stopped", "抢场已停止。"))
            return

        self.events.put(("log", f"抢场条件已生效：{rush_config_label(config)}"))
        self.events.put(
            ("log", f"正在打开浏览器。若尚未登录，请先完成交我办登录，程序会等待到 "
            f"{config.release_time.strftime('%H:%M:%S')} 自动抢场。")
        )

        ordered_slot: Slot | None = None
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    USER_DATA_DIR,
                    headless=False,
                    viewport={"width": 1400, "height": 950},
                )
                page = self._find_or_open_venue_page(context, config.venue)
                self._wait_for_booking_page(page, PlaywrightTimeoutError, config)

                if self.stop_event.is_set():
                    context.close()
                    return

                self._wait_for_release_time(config)
                if self.stop_event.is_set():
                    context.close()
                    return

                self.events.put(("status", "抢场中"))
                ordered_slot = self._rush_until_deadline(page, PlaywrightTimeoutError, config)

                if ordered_slot:
                    self.events.put(("ordered", ordered_slot))
                    self.events.put(("log", "已停止自动操作，浏览器会保持打开供你确认订单。"))
                    self._hold_browser_open()
                elif self.stop_event.is_set():
                    if self._user_stop_requested:
                        self.events.put(("log", "抢场已手动停止。"))
                    else:
                        self.events.put(("failed", "抢场自动操作已停止。浏览器页面会保留打开供你查看。"))
                        self.events.put(("log", "浏览器页面已保留；需要关闭时请点击“停止抢场”。"))
                        self._hold_browser_open()
                else:
                    self.events.put(("failed", "没有抢到目标时间段的场地，抢场已停止。浏览器页面会保留打开供你查看。"))
                    self.events.put(("log", "浏览器页面已保留；需要关闭时请点击“停止抢场”。"))
                    self._hold_browser_open()

                context.close()
        except RequestRateLimited as exc:
            self.events.put(("failed", str(exc)))
        except Exception as exc:
            self.events.put(("error", f"抢场器启动或执行失败：{exc}"))
        finally:
            if ordered_slot:
                self.events.put(("stopped", "抢场器已停止，浏览器窗口已关闭。"))
            else:
                self.events.put(("stopped", "抢场已停止。"))

    def _wait_for_booking_page(self, page, timeout_error_type, config: RushConfig) -> None:
        while not self.stop_event.is_set() and is_rush_start_allowed(release_time=config.release_time):
            try:
                self._ensure_rush_venue_page(page, config)
                self.events.put(("log", "预约页已就绪。"))
                return
            except RequestRateLimited:
                raise
            except BookingPageNotReady as exc:
                self._log_ready_wait(str(exc))
            except timeout_error_type as exc:
                self._log_ready_wait(f"正在等待预约页加载：{exc}")
            except Exception as exc:
                self._log_ready_wait(f"正在等待预约页就绪：{exc}")
            self._wait_interruptibly(0.5)

        if not self.stop_event.is_set():
            raise RuntimeError("抢场时间已过，预约页仍未就绪。")

    def _ensure_rush_venue_page(self, page, config: RushConfig) -> None:
        self._ensure_booking_page(page, config.venue)

    def _wait_for_release_time(self, config: RushConfig) -> None:
        release_at = rush_release_datetime(release_time=config.release_time)
        if dt.datetime.now() >= release_at:
            return

        self.events.put(("status", f"等待 {config.release_time.strftime('%H:%M:%S')}"))
        self.events.put(("log", f"预约页已打开，等待 {release_at.strftime('%H:%M:%S')} 刷新抢场。"))
        while not self.stop_event.is_set():
            remaining = (release_at - dt.datetime.now()).total_seconds()
            if remaining <= 0:
                break
            self._wait_interruptibly(min(remaining, 0.1))

    def _rush_until_deadline(self, page, timeout_error_type, config: RushConfig) -> Slot | None:
        deadline = rush_deadline_datetime(release_time=config.release_time)
        needs_reload = True
        target_date_selected = False
        reload_count = 0

        while not self.stop_event.is_set() and dt.datetime.now() < deadline:
            try:
                if needs_reload:
                    if reload_count == 0:
                        self.events.put(("log", f"{config.release_time.strftime('%H:%M:%S')} 到，正在刷新预约页。"))
                    else:
                        self.events.put(("log", "目标日期还没出现，再刷新一次预约页。"))
                    self._reload_booking_page(page, timeout_error_type)
                    reload_count += 1
                    needs_reload = False
                    target_date_selected = False

                if not self._wait_for_refreshed_booking_page(page, timeout_error_type, config, deadline):
                    return None

                if not target_date_selected:
                    date_state = self._date_tab_state(page, config.target_date)
                    action = date_bar_action(date_state["ready"], date_state["target_found"])
                    if action == "wait":
                        self._log_attempt_wait(
                            f"刷新后日期标签还没加载完整（当前 {date_state['date_count']} 个），继续等待当前页面。"
                        )
                        self._wait_interruptibly(0.3)
                        continue
                    if action == "reload":
                        self.events.put(("log", f"日期条已出现，但没有 {config.target_date.isoformat()}，立即刷新预约页。"))
                        needs_reload = True
                        continue

                    try:
                        self._select_target_date(page, timeout_error_type, config.target_date, config.venue)
                    except RuntimeError as exc:
                        self._log_attempt_wait(f"目标日期已出现但暂时点不到，继续等待当前页面：{exc}")
                        self._wait_interruptibly(0.2)
                        continue
                    target_date_selected = True
                    page.wait_for_timeout(300)

                self._raise_if_rate_limited(page)

                return self._try_configured_time_slots(page, config, deadline)
            except RequestRateLimited:
                raise
            except Exception as exc:
                if self._is_page_closed_error(exc):
                    self.events.put(("log", "浏览器页面已关闭，抢场停止。"))
                    self._stop_automatically(keep_browser_open=False)
                    return None
                self._log_attempt_wait(f"本轮抢场未完成：{exc}")

            self._wait_interruptibly(0.2)

        return None

    def _try_configured_time_slots(
        self,
        page,
        config: RushConfig,
        deadline: dt.datetime,
    ) -> Slot | None:
        priority_labels = (
            "第一时间",
            "第二时间",
            "第三时间",
            "第四时间",
            "第五时间",
            "第六时间",
            "第七时间",
        )
        for index, time_slot in enumerate(config.time_slots):
            priority_label = priority_labels[index]
            time_label = f"{time_slot.start_hour:02d}:00-{time_slot.end_hour:02d}:00"
            self.events.put(("log", f"开始{priority_label} {time_label}。"))

            if not self._wait_for_target_grid_ready(page, time_slot, deadline):
                return None

            ordered_slot = self._try_order_current_grid(
                page,
                config,
                time_slot,
                deadline,
            )
            if ordered_slot:
                return ordered_slot
            if self.stop_event.is_set() or dt.datetime.now() >= deadline:
                return None
            if index + 1 < len(config.time_slots):
                next_label = priority_labels[index + 1]
                self.events.put(("log", f"{priority_label}全部失败，切换{next_label}。"))

        return None

    def _reload_booking_page(self, page, timeout_error_type) -> None:
        if page.is_closed():
            raise RuntimeError("浏览器页面已关闭")
        try:
            page.reload(wait_until="domcontentloaded", timeout=12000)
        except timeout_error_type:
            self.events.put(("log", "刷新响应较慢，先等待当前页面加载，不立即重复刷新。"))

    def _wait_for_refreshed_booking_page(self, page, timeout_error_type, config: RushConfig, deadline: dt.datetime) -> bool:
        while not self.stop_event.is_set() and dt.datetime.now() < deadline:
            try:
                if page.is_closed():
                    raise RuntimeError("浏览器页面已关闭")
                self._ensure_booking_page(page, config.venue)
                return True
            except RequestRateLimited:
                raise
            except BookingPageNotReady as exc:
                self._log_attempt_wait(f"刷新后页面还在加载：{exc}")
            except timeout_error_type as exc:
                self._log_attempt_wait(f"刷新后页面还在加载：{exc}")
            except Exception as exc:
                if self._is_page_closed_error(exc):
                    self.events.put(("log", "浏览器页面已关闭，抢场停止。"))
                    self._stop_automatically(keep_browser_open=False)
                    return False
                self._log_attempt_wait(f"刷新后页面还在加载：{exc}")
            self._wait_interruptibly(0.3)
        return False

    def _date_tab_state(self, page, target_date: dt.date) -> dict[str, object]:
        labels = [self._normalize_text(label) for label in target_date_labels(target_date)]
        result = page.evaluate(
            grid_probe("labels, readyCount", """
              const bodyText = norm(document.body.innerText);
              const texts = visibleElements()
                .map((el) => norm(el.innerText || el.textContent || ''))
                .filter(Boolean);
              const dateTexts = new Set(
                texts.filter((text) =>
                  /\\d{1,2}月\\d{1,2}日/.test(text) ||
                  /\\d{4}-\\d{2}-\\d{2}/.test(text)
                )
              );
              return {
                ready: dateTexts.size >= readyCount,
                targetFound: labels.some((label) => bodyText.includes(label)),
                dateCount: dateTexts.size,
              };
            }
            """),
            grid_arguments(labels=labels, readyCount=DATE_TAB_READY_COUNT),
        )
        return {
            "ready": bool(result.get("ready")),
            "target_found": bool(result.get("targetFound")),
            "date_count": int(result.get("dateCount") or 0),
        }

    def _wait_for_target_grid_ready(
        self,
        page,
        time_slot: RushTimeSlot,
        deadline: dt.datetime,
    ) -> bool:
        while not self.stop_event.is_set() and dt.datetime.now() < deadline:
            state = self._target_grid_state(page, time_slot)
            if state["ready"]:
                return True
            self._log_attempt_wait(f"等待场地图加载：{state['reason']}")
            self._wait_interruptibly(0.2)
        return False

    def _target_grid_state(self, page, time_slot: RushTimeSlot) -> dict[str, object]:
        return page.evaluate(
            grid_probe("targetHour", """
              const all = visibleElements();
              const bodyText = norm(document.body.innerText);

              const loadingSelectors = [
                '.el-loading-mask',
                '.el-loading-spinner',
                '.ant-spin-spinning',
                '.van-loading',
                '.loading',
                '[class*="loading"]',
                '[class*="spin"]'
              ];
              const hasLoading = loadingSelectors.some((selector) =>
                Array.from(document.querySelectorAll(selector)).some(visible)
              ) || /加载中|正在加载/.test(bodyText);
              if (hasLoading) {
                return { ready: false, reason: '页面仍在加载' };
              }

              const timeNodes = all
                .map((el) => ({ text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^\\d{2}:00$/.test(item.text));
              const courtNodes = all
                .map((el) => ({ text: norm(el.innerText || el.textContent || ''), rect: el.getBoundingClientRect() }))
                .filter((item) => /^场地\\d+$/.test(item.text));

              const targetTime = timeNodes.find((item) => item.text === targetHour);
              if (!targetTime) {
                return { ready: false, reason: `还没看到 ${targetHour} 时间行` };
              }

              const courtSet = new Set(courtNodes.map((item) => item.text));
              for (let court = 1; court <= geom.courtCount; court += 1) {
                if (!courtSet.has(`场地${court}`)) {
                  return { ready: false, reason: `还没看到场地${court}` };
                }
              }

              const bounds = gridBounds(courtNodes, timeNodes);
              const rowCenterY = targetTime.rect.top + targetTime.rect.height / 2;
              const candidates = all
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .filter((item) =>
                  boxInsideGrid(item.rect, bounds) &&
                  boxIsGridCell(item.rect) &&
                  rowDistance(item.rect, rowCenterY) <= geom.maxRowDistance
                );

              return {
                ready: candidates.length >= geom.courtCount,
                reason: candidates.length >= geom.courtCount ? '场地图已加载' : `目标时间行只有 ${candidates.length} 个格子`
              };
            }
            """),
            grid_arguments(targetHour=f"{time_slot.start_hour:02d}:00"),
        )

    def _normalize_text(self, text: str) -> str:
        return "".join((text or "").split())

    def _is_page_closed_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "target page" in message and "closed" in message
            or "context or browser has been closed" in message
            or "浏览器页面已关闭" in message
        )

    def _try_order_current_grid(
        self,
        page,
        config: RushConfig,
        time_slot: RushTimeSlot,
        deadline: dt.datetime,
    ) -> Slot | None:
        allowed_courts = rush_allowed_courts(
            config.venue.key,
            config.huxiaoming_court_scope,
        )
        court_order = rush_court_attempt_order(config.preferred_court, allowed_courts)
        for court in court_order:
            if self.stop_event.is_set() or dt.datetime.now() >= deadline:
                return None

            slot = Slot(
                venue_key=config.venue.key,
                venue=config.venue.name,
                date=config.target_date,
                court=f"场地{court}",
                hour=f"{time_slot.start_hour:02d}:00",
            )

            try:
                self._clear_transient_notices(page)
                self.events.put(("log", f"尝试下单：{slot.venue} {slot.date.isoformat()} {slot.hour} {slot.court}"))
                cell_state = self._slot_cell_state(page, slot)
                cell_state_name = str(cell_state.get("state", ""))
                if not slot_cell_can_submit(cell_state_name):
                    self.events.put(("log", f"{slot.court} 不是蓝色可选格子，跳过：{cell_state['reason']}"))
                    continue

                selected_order_matches = self._selected_order_matches_slot(page, slot)
                if slot_cell_needs_click(cell_state_name, selected_order_matches):
                    self._try_select_slot_cell(page, slot, cell_state)
                    if not self._wait_for_slot_selected(page, slot):
                        self.events.put(("log", f"{slot.court} 点击后没有确认选中，继续尝试下一个场地。"))
                        continue
                else:
                    self.events.put(("log", f"{slot.court} 已经在订单栏中确认选中，继续下单。"))

                failure = self._failure_notice_text(page)
                if failure:
                    self.events.put(("log", f"{slot.court} 已不可用：{failure}"))
                    continue

                self._click_visible_text_button(page, "立即下单", timeout=1500)
                page.wait_for_timeout(180)
                failure = self._failure_notice_text(page)
                if failure:
                    self.events.put(("log", f"{slot.court} 下单前已失败：{failure}"))
                    continue

                if not self._accept_booking_notice_fast(page):
                    self.events.put(("log", "没有确认勾选预订须知，停止自动操作以避免误提交。"))
                    self._stop_automatically()
                    return None

                self._click_visible_text_button(page, "提交订单", timeout=2000)
                result_kind, result_text = self._wait_for_order_result(page)
                if result_kind == "success":
                    self.events.put(
                        ("log", f"已确认抢场成功：{slot.venue} {slot.date.isoformat()} "
                        f"{slot.hour}-{time_slot.end_hour:02d}:00 {slot.court}")
                    )
                    return slot
                if result_kind == "failure":
                    self.events.put(("log", f"{slot.court} 提交失败：{result_text}"))
                    continue

                self.events.put(("log", f"{slot.court} 提交后没有看到明确成功或失败：{result_text}。停止自动操作以避免重复下单。"))
                self._stop_automatically()
                return None
            except Exception as exc:
                if self._is_page_closed_error(exc):
                    self.events.put(("log", "浏览器页面已关闭，抢场停止。"))
                    self._stop_automatically(keep_browser_open=False)
                    return None
                self.events.put(("log", f"{slot.court} 未抢到，继续尝试下一个场地：{exc}"))

        return None

    def _hold_browser_open(self) -> None:
        while not self._close_browser_event.wait(0.2):
            pass

    def _stop_automatically(self, keep_browser_open: bool = True) -> None:
        if not keep_browser_open:
            self._signal_close_browser()
        self.stop_event.set()
        self.wake_event.set()

    def _signal_close_browser(self) -> None:
        self._close_browser_event.set()

    def _wait_interruptibly(self, seconds: float) -> None:
        if self.wake_event.wait(seconds):
            self.wake_event.clear()

    def _log_ready_wait(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_ready_log_at >= 5:
            self._last_ready_log_at = now
            self.events.put(("log", message))

