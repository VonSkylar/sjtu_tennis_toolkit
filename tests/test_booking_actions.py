import queue
import unittest

from sjtu_tennis_toolkit.browser.monitor import VenueMonitor


class FakeNoticePage:
    """Minimal page stub: every probe returns the same body text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.scripts: list[str] = []

    def evaluate(self, script: str, arg=None):
        self.scripts.append(script)
        return self.text


class NoticeReadingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = VenueMonitor(lambda: None, queue.Queue())

    def test_success_toast_is_recognised(self) -> None:
        self.assertEqual(
            self.monitor._success_notice_text(FakeNoticePage("订单提交成功")),
            "订单提交成功",
        )

    def test_failure_toast_is_recognised(self) -> None:
        self.assertEqual(
            self.monitor._failure_notice_text(FakeNoticePage("该场地已被预约，请重新选择时段")),
            "该场地已被预约，请重新选择时段",
        )

    def test_neutral_toast_matches_neither(self) -> None:
        page = FakeNoticePage("正在提交，请稍候")
        self.assertEqual(self.monitor._success_notice_text(page), "")
        self.assertEqual(self.monitor._failure_notice_text(page), "")

    def test_empty_toast_is_not_mistaken_for_failure(self) -> None:
        page = FakeNoticePage("")
        self.assertEqual(self.monitor._failure_notice_text(page), "")
        self.assertEqual(self.monitor._success_notice_text(page), "")


if __name__ == "__main__":
    unittest.main()
