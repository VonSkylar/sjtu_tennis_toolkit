"""VenueMonitor — Playwright browser-based booking page monitor."""

from __future__ import annotations

import datetime as dt
import queue
import re
import threading
import time

from sjtu_tennis_toolkit.browser.booking_actions import (
    BookingPageActions,
    slot_cell_can_submit,
    slot_cell_needs_click,
)
from sjtu_tennis_toolkit.browser.js_snippets import grid_arguments, grid_probe
from sjtu_tennis_toolkit.constants import (
    AUTO_ORDER_RETRY_COOLDOWN_SECONDS,
    DEFAULT_CHECK_INTERVAL_SECONDS,
    DEBUG_PAGE_LIST_SECONDS,
    SETUP_SCAN_SECONDS,
    USER_DATA_DIR,
)
from sjtu_tennis_toolkit.config import (
    config_label,
    court_matches_monitor_scope,
    next_rate_limit_retry_time,
    save_rate_limit_cooldown,
    target_date_labels,
)
from sjtu_tennis_toolkit.exceptions import BookingPageNotReady, RequestRateLimited
from sjtu_tennis_toolkit.models import MonitorConfig, Slot, Venue, VENUES_BY_KEY


class VenueMonitor(BookingPageActions):
    def __init__(self, config_provider, events: queue.Queue) -> None:
        super().__init__()
        self.config_provider = config_provider
        self.events = events
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self._last_page_debug_at = 0.0
        self._last_not_ready_log_at = 0.0
        self._last_config: MonitorConfig | None = None
        self._next_date_index_by_venue: dict[str, int] = {}
        self._pages_by_venue: dict[str, object] = {}
        self._auto_order_halted = False
        self._auto_order_last_attempt_at: dict[str, float] = {}

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def wake(self) -> None:
        self.wake_event.set()

    def run(self) -> None:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.events.put(("error", "缺少 Playwright。请先运行：pip install -r requirements.txt，然后运行：python -m playwright install chromium"))
            return

        self.events.put(("log", "正在打开浏览器。若尚未登录，请先完成交我办登录。程序会按所选场馆打开网球场预约页。"))

        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    USER_DATA_DIR,
                    headless=False,
                    viewport={"width": 1400, "height": 950},
                )
                while not self.stop_event.is_set():
                    wait_seconds = self._current_check_interval()
                    try:
                        config = self.config_provider()
                        wait_seconds = config.check_interval_seconds
                        if config != self._last_config:
                            self._last_config = config
                            self._next_date_index_by_venue = {venue.key: 0 for venue in config.venues}
                            self.events.put(("log", f"监控条件已生效：{config_label(config)}"))

                        all_slots = []
                        checked_dates = []
                        venue_not_ready = []
                        venue_errors = []
                        for venue in config.venues:
                            try:
                                page = self._find_or_open_venue_page(context, venue)
                                slots, checked_date = self._check_once(page, PlaywrightTimeoutError, config, venue)
                            except RequestRateLimited:
                                raise
                            except BookingPageNotReady as exc:
                                venue_not_ready.append(f"{venue.name}：{exc}")
                                continue
                            except Exception as exc:
                                venue_errors.append(f"{venue.name}：{exc}")
                                continue
                            checked_dates.append((venue, checked_date))
                            all_slots.extend(slots)

                        if all_slots:
                            self.events.put(("available", all_slots))
                            self._maybe_auto_order_unique_slot(config, all_slots)
                        elif checked_dates:
                            checked_at = dt.datetime.now().strftime("%H:%M:%S")
                            checked = "；".join(f"{venue.name} {checked_date.isoformat()}" for venue, checked_date in checked_dates)
                            self.events.put(("log", f"{checked_at} {checked} 未发现目标时段空场，{config.check_interval_seconds} 秒后检查下一轮。"))
                            if venue_not_ready or venue_errors:
                                self.events.put(("log", "部分场馆本轮未完成：" + "；".join(venue_not_ready + venue_errors)))
                        elif venue_not_ready and not venue_errors:
                            raise BookingPageNotReady("；".join(venue_not_ready))
                        elif venue_errors:
                            raise RuntimeError("；".join(venue_errors))
                    except ValueError as exc:
                        wait_seconds = SETUP_SCAN_SECONDS
                        self._log_not_ready(f"监控条件暂未生效：{exc}")
                    except BookingPageNotReady as exc:
                        wait_seconds = SETUP_SCAN_SECONDS
                        self._log_not_ready(str(exc))
                    except RequestRateLimited as exc:
                        retry_at = next_rate_limit_retry_time()
                        save_rate_limit_cooldown(retry_at)
                        self.events.put(("error", f"{exc}\n\n今天请求额度已经用完，建议不要继续刷新。程序已停止监控，可在 {retry_at.strftime('%Y-%m-%d %H:%M')} 后再试。"))
                        self.stop_event.set()
                        break
                    except Exception as exc:  # Keep polling through transient page changes.
                        self.events.put(("log", f"本轮检查未完成：{exc}"))
                        wait_seconds = self._current_check_interval()

                    self._sleep_interruptibly(wait_seconds)

                context.close()
        except Exception as exc:
            self.events.put(("error", f"浏览器监控启动失败：{exc}"))
        finally:
            self.events.put(("stopped", "监控已停止。"))

    def _find_or_open_venue_page(self, context, venue: Venue):
        cached = self._pages_by_venue.get(venue.key)
        if cached and not cached.is_closed():
            if self._should_navigate_to_venue(cached.url, venue):
                self.events.put(("log", f"登录后当前页面不是 {venue.name} 预约页，正在自动跳转。"))
                cached.goto(venue.url, wait_until="domcontentloaded")
            self.events.put(("log", f"正在监控 {venue.name} 标签页：{self._page_label(cached)}"))
            return cached

        page = self._find_existing_venue_page(context, venue)
        if page:
            self._pages_by_venue[venue.key] = page
            return page

        if self._find_login_page(context):
            raise BookingPageNotReady("正在等待已打开的 jAccount 标签页完成登录。两个场馆只需登录一次，登录成功后程序会自动打开其它场馆。")

        page = self._find_blank_page(context) or context.new_page()
        self._pages_by_venue[venue.key] = page
        self.events.put(("log", f"正在打开 {venue.name} 预约页。"))
        page.goto(venue.url, wait_until="domcontentloaded")
        return page

    def _is_blank_page(self, page) -> bool:
        url = (page.url or "").lower()
        return url in {"", "about:blank"} or url.startswith("chrome://newtab")

    def _is_login_url(self, url: str) -> bool:
        return "jaccount.sjtu.edu.cn" in (url or "").lower()

    def _should_navigate_to_venue(self, url: str, venue: Venue) -> bool:
        if self._is_login_url(url):
            return False
        return not self._looks_like_venue_url(url, venue)

    def _find_blank_page(self, context):
        for page in context.pages:
            if not page.is_closed() and self._is_blank_page(page):
                return page
        return None

    def _find_login_page(self, context):
        for page in context.pages:
            if not page.is_closed() and self._is_login_url(page.url):
                return page
        return None

    def _redirect_misaligned_venue_pages(self) -> None:
        for venue_key, page in list(self._pages_by_venue.items()):
            if page.is_closed():
                continue
            venue = VENUES_BY_KEY.get(venue_key)
            if not venue or self._looks_like_venue_url(page.url, venue):
                continue
            try:
                self.events.put(("log", f"登录已完成，正在立即打开 {venue.name} 预约页。"))
                page.goto(venue.url, wait_until="domcontentloaded")
            except Exception as exc:
                self.events.put(("log", f"{venue.name} 登录后自动跳转未完成：{exc}"))

    def _find_existing_venue_page(self, context, venue: Venue):
        candidates = list(context.pages)

        self._log_visible_pages(candidates)

        url_matches = []
        for candidate in candidates:
            if candidate.is_closed():
                continue
            url = candidate.url.lower()
            if url in {"", "about:blank"} or url.startswith("chrome://newtab"):
                continue
            if self._looks_like_venue_url(url, venue):
                url_matches.append(candidate)

        for candidate in url_matches:
            self.events.put(("log", f"正在监控 {venue.name} 标签页：{self._page_label(candidate)}"))
            return candidate

        return None

    def _sleep_interruptibly(self, seconds: int) -> None:
        end_at = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < end_at:
            if self.wake_event.wait(0.2):
                self.wake_event.clear()
                break

    def _current_check_interval(self) -> int:
        if self._last_config:
            return self._last_config.check_interval_seconds
        return DEFAULT_CHECK_INTERVAL_SECONDS

    def _maybe_auto_order_unique_slot(self, config: MonitorConfig, slots: list[Slot]) -> None:
        if not config.auto_order_enabled:
            return
        if self._auto_order_halted:
            return
        if len(slots) != 1:
            self.events.put(("log", f"本轮发现 {len(slots)} 个符合条件的空场，按设置不自动下单，只报警。"))
            return

        slot = slots[0]
        slot_key = self._slot_key(slot)
        attempted_at = self._auto_order_last_attempt_at.get(slot_key)
        if attempted_at is not None and time.monotonic() - attempted_at < AUTO_ORDER_RETRY_COOLDOWN_SECONDS:
            # The grid often lags behind a rejected submit; without this guard the
            # same cell is re-detected as "the only free slot" every round.
            return

        self._auto_order_last_attempt_at[slot_key] = time.monotonic()
        try:
            result_kind, result_text = self._auto_order_slot(slot)
        except Exception as exc:
            self.events.put(("log", f"自动下单未完成，本轮不计入成功：{exc}"))
            return

        if result_kind == "success":
            self._halt_auto_order("已经自动下单成功")
            self.events.put(("log", f"已确认自动下单成功：{self._slot_text(slot)}（{result_text}）"))
            self.events.put(("ordered", slot))
            return

        if result_kind == "failure":
            self.events.put(
                ("log", f"自动下单失败：{result_text}（{self._slot_text(slot)}）；"
                f"{AUTO_ORDER_RETRY_COOLDOWN_SECONDS} 秒内不再重试该格子。")
            )
            return

        self._halt_auto_order("提交结果不明确")
        self.events.put(
            ("log",
             f"自动下单提交后没有看到明确成功或失败提示：{result_text}。"
             "为避免重复下单，已停止后续自动下单，请到浏览器确认订单结果。")
        )

    def _halt_auto_order(self, reason: str) -> None:
        if self._auto_order_halted:
            return
        self._auto_order_halted = True
        self.events.put(("log", f"已关闭自动下单（{reason}）。监控继续运行，只报警不下单。"))

    def _slot_key(self, slot: Slot) -> str:
        return f"{slot.venue_key}|{slot.date.isoformat()}|{slot.hour}|{slot.court}"

    def _slot_text(self, slot: Slot) -> str:
        return f"{slot.venue} {slot.date.isoformat()} {slot.hour} {slot.court}"

    def _auto_order_slot(self, slot: Slot) -> tuple[str, str]:
        """Select the cell, submit, and read the result back.

        Returns ("success"|"failure"|"unknown", text). A submit is only reported
        as done when the page confirms it, so a silent failure can never be
        mistaken for a placed order.
        """
        page = self._pages_by_venue.get(slot.venue_key)
        if not page or page.is_closed():
            raise RuntimeError(f"找不到 {slot.venue} 的预约标签页")

        self.events.put(("log", f"唯一符合条件空场，开始自动下单：{self._slot_text(slot)}"))
        self._clear_transient_notices(page)

        if not self._select_slot_for_order(page, slot):
            raise RuntimeError(f"{slot.court} {slot.hour} 无法确认已选中，已放弃本次自动下单")

        failure = self._failure_notice_text(page)
        if failure:
            return "failure", failure

        self._click_visible_text_button(page, "立即下单", timeout=3000)
        page.wait_for_timeout(180)
        failure = self._failure_notice_text(page)
        if failure:
            return "failure", failure

        if not self._accept_booking_notice_fast(page):
            raise RuntimeError("没有确认勾选预订须知，已放弃本次自动下单以避免误提交")

        self._click_visible_text_button(page, "提交订单", timeout=3000)
        return self._wait_for_order_result(page)

    def _select_slot_for_order(self, page, slot: Slot) -> bool:
        """Click the target cell if needed and verify it reached the order bar."""
        cell_state = self._slot_cell_state(page, slot)
        state_name = str(cell_state.get("state", ""))

        if slot_cell_can_submit(state_name):
            if not slot_cell_needs_click(state_name, self._selected_order_matches_slot(page, slot)):
                self.events.put(("log", f"{slot.court} 已经在订单栏中确认选中，继续下单。"))
                return True
            self._try_select_slot_cell(page, slot, cell_state)
            return self._wait_for_slot_selected(page, slot)

        if state_name == "unknown" and cell_state.get("x") is not None:
            # The scanner (4-level ancestor text/colour match) and this probe
            # (geometric cell) can disagree; click anyway but still require the
            # order bar to confirm before anything is submitted.
            self.events.put(("log", f"{slot.court} 格子状态无法确认（{cell_state.get('reason')}），先点击并用订单栏回读校验。"))
            self._try_select_slot_cell(page, slot, cell_state)
            return self._wait_for_slot_selected(page, slot)

        self.events.put(("log", f"{slot.court} 不是可下单格子（{cell_state.get('reason')}），本次不下单。"))
        return False

    def _log_not_ready(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_not_ready_log_at >= 5:
            self._last_not_ready_log_at = now
            self.events.put(("log", message))

    def _looks_like_venue_url(self, url: str, venue: Venue) -> bool:
        venue_id = self._appointment_id_from_url(venue.url)
        return bool(venue_id and venue_id in (url or "").lower())

    def _appointment_id_from_url(self, url: str) -> str:
        match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", url.lower())
        return match.group(0) if match else ""

    def _has_booking_grid(self, page) -> bool:
        try:
            return bool(
                page.locator("text=场地1").count() > 0
                and (page.locator("text=07:00").count() > 0 or page.locator("text=08:00").count() > 0)
            )
        except Exception:
            return False

    def _log_visible_pages(self, pages) -> None:
        now = time.monotonic()
        if now - self._last_page_debug_at < DEBUG_PAGE_LIST_SECONDS:
            return
        self._last_page_debug_at = now
        labels = [self._page_label(page) for page in pages if not page.is_closed()]
        if labels:
            self.events.put(("log", "程序当前能看到的标签页：" + "；".join(labels)))
        else:
            self.events.put(("log", "程序当前没有看到任何浏览器标签页。"))

    def _page_label(self, page) -> str:
        try:
            title = page.title(timeout=800).strip()
        except Exception:
            title = ""
        url = (page.url or "").strip()
        if len(url) > 90:
            url = url[:87] + "..."
        return f"\u201c{title or '无标题'}\u201d {url or '无地址'}"

    def _check_once(self, page, timeout_error_type, config: MonitorConfig, venue: Venue) -> tuple[list[Slot], dt.date]:
        self._ensure_booking_page(page, venue)
        next_date_index = self._next_date_index_by_venue.get(venue.key, 0) % len(config.dates)
        for offset in range(len(config.dates)):
            index = (next_date_index + offset) % len(config.dates)
            target_date = config.dates[index]
            try:
                self._select_target_date(page, timeout_error_type, target_date, venue)
            except RuntimeError as exc:
                self.events.put(("log", f"{venue.name} {target_date.isoformat()} 暂未检查：{exc}"))
                continue

            self._next_date_index_by_venue[venue.key] = (index + 1) % len(config.dates)
            page.wait_for_timeout(900)
            self._raise_if_rate_limited(page)
            slots = self._extract_available_slots(page, config, target_date, venue)
            return slots, target_date

        raise RuntimeError("没有任何目标日期在页面日期标签中开放。")

    def _ensure_booking_page(self, page, venue: Venue) -> None:
        text = page.locator("body").inner_text(timeout=3000)
        self._handle_login_page(page, text)
        has_target_url = self._looks_like_venue_url(page.url, venue)
        has_target_grid = venue.name in text and self._has_booking_grid(page)
        if not (has_target_url or has_target_grid):
            self.events.put(("log", f"当前页面不是 {venue.name} 预约页，正在立即打开具体预约页。"))
            page.goto(venue.url, wait_until="domcontentloaded")
            raise BookingPageNotReady(f"已打开 {venue.name} 预约页，等待页面加载完成。")
        self._redirect_misaligned_venue_pages()
        if "每日请求超过限制" in text or "请求超过限制" in text:
            raise RequestRateLimited("学校系统提示\u201c每日请求超过限制，无法获取\u201d。")

    def _handle_login_page(self, page, text: str) -> None:
        compact = re.sub(r"\s+", "", text or "")
        url = (page.url or "").lower()

        if "jaccount.sjtu.edu.cn" in url or "统一身份认证" in compact or "登录jAccount" in compact:
            raise BookingPageNotReady("正在等待 jAccount 登录。请扫码或输入验证码完成登录；登录成功后程序会继续监控，并复用本地浏览器会话。")

        if "校内人员登录" in compact:
            try:
                page.get_by_text("校内人员登录", exact=True).click(timeout=1500)
            except Exception:
                try:
                    page.get_by_role("button", name=re.compile("校内人员登录")).click(timeout=1500)
                except Exception as exc:
                    raise BookingPageNotReady(f"检测到未登录，但没有点到\u201c校内人员登录\u201d：{exc}") from exc
            raise BookingPageNotReady("检测到未登录，已自动点击\u201c校内人员登录\u201d。如进入 jAccount 页面，请手动完成一次登录。")

    def _raise_if_rate_limited(self, page) -> None:
        text = page.locator("body").inner_text(timeout=3000)
        if "每日请求超过限制" in text or "请求超过限制" in text:
            raise RequestRateLimited("学校系统提示\u201c每日请求超过限制，无法获取\u201d。")

    def _has_request_too_frequent_notice(self, page) -> bool:
        text = page.locator("body").inner_text(timeout=3000)
        return "请求过于频繁" in re.sub(r"\s+", "", text or "")

    def _select_target_date(self, page, timeout_error_type, target_date: dt.date, venue: Venue) -> None:
        for label in target_date_labels(target_date):
            locator = page.get_by_text(label, exact=False).first
            try:
                if locator.count() > 0:
                    locator.click(timeout=1200)
                    self.events.put(("log", f"{venue.name} 已切换到目标日期：{label}"))
                    return
            except timeout_error_type:
                continue
        raise RuntimeError("目标日期暂未开放预约，或页面日期标签中未找到该日期。")

    def _extract_available_slots(self, page, config: MonitorConfig, target_date: dt.date, venue: Venue) -> list[Slot]:
        target_hours = [f"{hour:02d}:00" for hour in range(config.start_hour, config.end_hour)]
        raw_slots = page.evaluate(
            grid_probe("targetHours", """
              const all = visibleElements();
              const bodyText = norm(document.body.innerText);

              const timeNodes = all
                .map((el) => ({ el, text: norm(el.innerText), rect: el.getBoundingClientRect() }))
                .filter((item) => /^\\d{2}:00$/.test(item.text) && targetHours.includes(item.text))
                .sort((a, b) => a.rect.top - b.rect.top);

              const courtNodes = all
                .map((el) => ({ el, text: norm(el.innerText), rect: el.getBoundingClientRect() }))
                .filter((item) => /^场地\\d+$/.test(item.text))
                .sort((a, b) => a.rect.left - b.rect.left);

              if (timeNodes.length === 0 || courtNodes.length === 0) {
                return { error: '没有识别到时间行或场地列。请确认页面停留在网球场预约表格。' };
              }

              const bounds = gridBounds(courtNodes, timeNodes);

              const isAvailable = (el) => {
                const chain = [];
                let current = el;
                for (let depth = 0; current && depth < geom.scannerChainDepth; depth += 1) {
                  chain.push(current);
                  current = current.parentElement;
                }

                const combined = chain.map((node) => {
                  const text = norm(node.innerText);
                  const title = norm(node.getAttribute('title'));
                  const aria = norm(node.getAttribute('aria-label'));
                  const klass = norm(node.className && node.className.toString());
                  const dataState = norm(node.getAttribute('data-state') || node.getAttribute('data-status'));
                  return `${text}|${title}|${aria}|${klass}|${dataState}`;
                }).join('|');

                if (/不可选|已约|已满|禁用|disabled|disable|unavailable|booked|sold|reserved/i.test(combined)) {
                  return false;
                }
                if (/可选|available|selectable|free|empty|enabled|optional|appointable/i.test(combined)) {
                  return true;
                }

                const colorText = chain.map((node) => {
                  const style = window.getComputedStyle(node);
                  return `${style.backgroundColor} ${style.borderColor} ${style.backgroundImage}`;
                }).join(' ').toLowerCase();
                const blueish = /rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/g;
                let match;
                while ((match = blueish.exec(colorText)) !== null) {
                  const r = Number(match[1]);
                  const g = Number(match[2]);
                  const b = Number(match[3]);
                  if (isSelectableBlue(r, g, b)) {
                    return true;
                  }
                }

                return false;
              };

              const candidates = all
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .filter((item) => boxInsideGrid(item.rect, bounds) && boxIsGridCell(item.rect))
                .filter((item) => isAvailable(item.el));

              const results = [];
              const seen = new Set();

              for (const item of candidates) {
                const centerX = item.rect.left + item.rect.width / 2;
                const centerY = item.rect.top + item.rect.height / 2;
                const hour = timeNodes.reduce((best, node) => {
                  const y = node.rect.top + node.rect.height / 2;
                  const distance = Math.abs(centerY - y);
                  return !best || distance < best.distance ? { node, distance } : best;
                }, null);
                const court = courtNodes.reduce((best, node) => {
                  const x = node.rect.left + node.rect.width / 2;
                  const distance = Math.abs(centerX - x);
                  return !best || distance < best.distance ? { node, distance } : best;
                }, null);

                if (!hour || !court || hour.distance > geom.maxRowDistance || court.distance > geom.maxColumnDistance) {
                  continue;
                }

                const key = `${court.node.text}-${hour.node.text}`;
                if (!seen.has(key)) {
                  seen.add(key);
                  results.push({ court: court.node.text, hour: hour.node.text });
                }
              }

              return {
                slots: results.sort((a, b) => a.hour.localeCompare(b.hour) || a.court.localeCompare(b.court)),
                candidateCount: candidates.length,
              };
            }
            """),
            grid_arguments(targetHours=target_hours),
        )

        if raw_slots.get("error"):
            raise RuntimeError(raw_slots["error"])

        candidate_count = raw_slots.get("candidateCount", 0)
        slot_items = raw_slots.get("slots", [])
        if candidate_count and not slot_items:
            self.events.put(("log", f"识别到 {candidate_count} 个蓝色候选，但没有匹配到目标时间行，请把页面滚动到目标时间段附近。"))

        return [
            Slot(
                venue_key=venue.key,
                venue=venue.name,
                date=target_date,
                court=item["court"],
                hour=item["hour"],
            )
            for item in slot_items
            if court_matches_monitor_scope(venue.key, item["court"], config)
        ]
