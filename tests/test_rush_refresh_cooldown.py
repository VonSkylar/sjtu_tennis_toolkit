import datetime as dt
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sjtu_tennis_toolkit.browser.monitor import VenueMonitor
from sjtu_tennis_toolkit.browser.rusher import RushBooker
from sjtu_tennis_toolkit.exceptions import RequestRateLimited
from sjtu_tennis_toolkit.models import VENUES_BY_KEY


class NoticePage:
    def __init__(self, notices: list[str], trace: list) -> None:
        self.url = VENUES_BY_KEY["east"].url
        self.notices = list(notices)
        self.trace = trace

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str):
        return SimpleNamespace(inner_text=lambda timeout: self.notices[0])

    def reload(self, **kwargs) -> None:
        self.trace.append("reload")
        if len(self.notices) > 1:
            self.notices.pop(0)


class RushRefreshCooldownTest(unittest.TestCase):
    def setUp(self) -> None:
        self.trace = []
        self.config = SimpleNamespace(
            venue=VENUES_BY_KEY["east"],
            target_date=dt.date(2026, 10, 12),
            release_time=dt.time(12),
        )
        self.booker = RushBooker(lambda: self.config, queue.Queue())
        self.deadline = dt.datetime.now() + dt.timedelta(minutes=1)
        self.booker.stop_event.wait = Mock(side_effect=self.record_wait)

    def record_wait(self, seconds: float) -> bool:
        self.trace.append(("wait", seconds))
        return False

    def wait_for_page(self, page) -> bool:
        return self.booker._wait_for_refreshed_booking_page(
            page, TimeoutError, self.config, self.deadline
        )

    def test_shared_detector_recognizes_notice_with_whitespace(self) -> None:
        monitor = VenueMonitor(lambda: None, queue.Queue())
        page = NoticePage(["请求过于\n频繁，请稍后再试"], self.trace)
        self.assertTrue(monitor._has_request_too_frequent_notice(page))
        page.notices = ["每日请求超过限制，无法获取"]
        self.assertFalse(monitor._has_request_too_frequent_notice(page))

    def test_notice_waits_one_second_before_each_retry(self) -> None:
        page = NoticePage(
            ["请求过于频繁，请稍后再试", "请求过于频繁，请稍后再试", "日期条已加载"],
            self.trace,
        )
        # A UI wake must not bypass the one-second wait.
        self.booker.wake_event.set()
        self.assertTrue(self.wait_for_page(page))
        self.assertEqual(
            self.trace, [("wait", 1.0), "reload", ("wait", 1.0), "reload"]
        )

    def test_normal_page_does_not_wait_or_reload(self) -> None:
        page = NoticePage(["日期条已加载"], self.trace)
        self.assertTrue(self.wait_for_page(page))
        self.assertEqual(self.trace, [])

    def test_stop_during_cooldown_prevents_reload(self) -> None:
        page = NoticePage(["请求过于频繁，请稍后再试"], self.trace)

        def stop_during_wait(seconds):
            self.record_wait(seconds)
            self.booker.stop()
            return True

        self.booker.stop_event.wait.side_effect = stop_during_wait
        self.assertFalse(self.wait_for_page(page))
        self.assertEqual(self.trace, [("wait", 1.0)])

    def test_deadline_during_cooldown_prevents_reload(self) -> None:
        page = NoticePage(["请求过于频繁，请稍后再试"], self.trace)
        now = dt.datetime.now()
        self.deadline = now + dt.timedelta(seconds=0.5)
        with patch("sjtu_tennis_toolkit.browser.rusher.dt") as clock:
            clock.datetime.now.side_effect = [now, self.deadline]
            self.assertFalse(self.wait_for_page(page))
        self.assertEqual(self.trace, [("wait", 1.0)])

    def test_daily_limit_still_stops_without_refresh(self) -> None:
        page = NoticePage(
            ["每日请求超过限制，无法获取；请求过于频繁，请稍后再试"], self.trace
        )
        with self.assertRaises(RequestRateLimited):
            self.wait_for_page(page)
        self.assertEqual(self.trace, [])

    def test_rush_recovers_when_notice_appears_while_dates_are_missing(self) -> None:
        page = NoticePage(["日期条尚未加载"], self.trace)
        ordered_slot = object()
        self.booker._has_request_too_frequent_notice = Mock(
            side_effect=[False, True, False]
        )
        self.booker._date_tab_state = Mock(side_effect=[
            {"ready": False, "target_found": False, "date_count": 0},
            {"ready": True, "target_found": True, "date_count": 8},
        ])
        self.booker._wait_interruptibly = Mock()
        self.booker._select_target_date = Mock()
        self.booker._try_configured_time_slots = Mock(return_value=ordered_slot)
        page.wait_for_timeout = Mock()

        with patch(
            "sjtu_tennis_toolkit.browser.rusher.rush_deadline_datetime",
            return_value=self.deadline,
        ):
            result = self.booker._rush_until_deadline(page, TimeoutError, self.config)

        self.assertIs(result, ordered_slot)
        self.assertEqual(self.trace, ["reload", ("wait", 1.0), "reload"])
        self.booker._wait_interruptibly.assert_called_once_with(0.3)
        self.booker._select_target_date.assert_called_once()
        self.booker._try_configured_time_slots.assert_called_once()


if __name__ == "__main__":
    unittest.main()
