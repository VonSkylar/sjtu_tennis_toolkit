import datetime as dt
import queue
import unittest

from sjtu_tennis_toolkit.browser.monitor import VenueMonitor
from sjtu_tennis_toolkit.constants import AUTO_ORDER_RETRY_COOLDOWN_SECONDS
from sjtu_tennis_toolkit.models import MonitorConfig, Slot, VENUES_BY_KEY


TARGET_DATE = dt.date(2026, 9, 23)


def make_config(auto_order_enabled: bool = True) -> MonitorConfig:
    return MonitorConfig(
        venues=(VENUES_BY_KEY["huxiaoming"],),
        dates=(TARGET_DATE,),
        start_hour=17,
        end_hour=22,
        check_interval_seconds=20,
        auto_order_enabled=auto_order_enabled,
        huxiaoming_court_scope="all",
    )


def make_slot(court: str = "场地6", hour: str = "19:00") -> Slot:
    venue = VENUES_BY_KEY["huxiaoming"]
    return Slot(
        venue_key=venue.key,
        venue=venue.name,
        date=TARGET_DATE,
        court=court,
        hour=hour,
    )


class AutoOrderGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.monitor = VenueMonitor(make_config, self.events)
        self.attempts: list[Slot] = []

    def _stub_result(self, kind: str, text: str = "") -> None:
        def fake_auto_order(slot: Slot):
            self.attempts.append(slot)
            return kind, text

        self.monitor._auto_order_slot = fake_auto_order

    def _drain(self) -> list[tuple[str, object]]:
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return items

    def _logs(self) -> list[str]:
        return [str(payload) for kind, payload in self._drain() if kind == "log"]

    def test_success_is_reported_and_never_repeated(self) -> None:
        self._stub_result("success", "预约成功")
        slot = make_slot()

        self.monitor._maybe_auto_order_unique_slot(make_config(), [slot])
        self.monitor._maybe_auto_order_unique_slot(make_config(), [slot])

        self.assertEqual(len(self.attempts), 1)

    def test_success_pushes_the_ordered_slot_to_the_gui(self) -> None:
        self._stub_result("success", "预约成功")
        slot = make_slot()

        self.monitor._maybe_auto_order_unique_slot(make_config(), [slot])

        ordered = [payload for kind, payload in self._drain() if kind == "ordered"]
        self.assertEqual(ordered, [slot])

    def test_failure_is_not_retried_within_the_cooldown(self) -> None:
        self._stub_result("failure", "已被预定")
        slot = make_slot()

        self.monitor._maybe_auto_order_unique_slot(make_config(), [slot])
        self.monitor._maybe_auto_order_unique_slot(make_config(), [slot])

        self.assertEqual(len(self.attempts), 1)

    def test_failed_slot_can_be_retried_after_the_cooldown(self) -> None:
        self._stub_result("failure", "已被预定")
        slot = make_slot()
        config = make_config()

        self.monitor._maybe_auto_order_unique_slot(config, [slot])
        key = self.monitor._slot_key(slot)
        self.monitor._auto_order_last_attempt_at[key] -= AUTO_ORDER_RETRY_COOLDOWN_SECONDS
        self.monitor._maybe_auto_order_unique_slot(config, [slot])

        self.assertEqual(len(self.attempts), 2)

    def test_unknown_result_halts_auto_order_for_later_slots(self) -> None:
        self._stub_result("unknown", "提交后没有看到明确成功或失败提示")

        self.monitor._maybe_auto_order_unique_slot(make_config(), [make_slot()])
        self.monitor._maybe_auto_order_unique_slot(
            make_config(),
            [make_slot(court="场地7", hour="20:00")],
        )

        self.assertEqual(len(self.attempts), 1)
        self.assertNotIn("ordered", [kind for kind, _ in self._drain()])

    def test_hard_failure_is_never_reported_as_a_placed_order(self) -> None:
        def boom(slot: Slot):
            self.attempts.append(slot)
            raise RuntimeError("找不到 胡晓明网球场 的预约标签页")

        self.monitor._auto_order_slot = boom

        self.monitor._maybe_auto_order_unique_slot(make_config(), [make_slot()])

        kinds = [kind for kind, _ in self._drain()]
        self.assertNotIn("ordered", kinds)

    def test_transient_error_leaves_other_slots_available(self) -> None:
        def flaky(slot: Slot):
            self.attempts.append(slot)
            if len(self.attempts) == 1:
                raise RuntimeError("目标时间行或场地列还没加载出来")
            return "success", "预约成功"

        self.monitor._auto_order_slot = flaky

        self.monitor._maybe_auto_order_unique_slot(make_config(), [make_slot()])
        self.monitor._maybe_auto_order_unique_slot(
            make_config(),
            [make_slot(court="场地7", hour="20:00")],
        )

        self.assertEqual(len(self.attempts), 2)

    def test_multiple_free_slots_are_never_ordered(self) -> None:
        self._stub_result("success", "预约成功")

        self.monitor._maybe_auto_order_unique_slot(
            make_config(),
            [make_slot(), make_slot(court="场地7")],
        )

        self.assertEqual(self.attempts, [])

    def test_disabled_auto_order_never_submits(self) -> None:
        self._stub_result("success", "预约成功")

        self.monitor._maybe_auto_order_unique_slot(
            make_config(auto_order_enabled=False),
            [make_slot()],
        )

        self.assertEqual(self.attempts, [])


if __name__ == "__main__":
    unittest.main()
