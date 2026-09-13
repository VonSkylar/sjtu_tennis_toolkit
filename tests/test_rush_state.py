import json
import tempfile
import unittest
from pathlib import Path

from sjtu_tennis_toolkit.config import (
    DEFAULT_RUSH_HUXIAOMING_COURT_SCOPE,
    DEFAULT_RUSH_PREFERRED_COURT,
    DEFAULT_RUSH_TIME_RANGES,
    DEFAULT_RUSH_VENUE_KEY,
    HUXIAOMING_COURT_SCOPE_ALL,
    HUXIAOMING_COURT_SCOPE_INDOOR,
    HUXIAOMING_COURT_SCOPE_OUTDOOR,
)
from sjtu_tennis_toolkit.rush_state import (
    DEFAULT_RUSH_RELEASE_TIME_TEXT,
    describe_rush_ui_state,
    load_rush_ui_state,
    normalize_rush_ui_state,
    save_rush_ui_state,
)


class NormalizeRushUiStateTest(unittest.TestCase):
    def test_empty_input_yields_shipped_defaults(self) -> None:
        state = normalize_rush_ui_state()
        self.assertEqual(state.venue_key, DEFAULT_RUSH_VENUE_KEY)
        self.assertEqual(
            state.huxiaoming_court_scope,
            DEFAULT_RUSH_HUXIAOMING_COURT_SCOPE,
        )
        self.assertEqual(state.court, DEFAULT_RUSH_PREFERRED_COURT)
        self.assertEqual(state.release_time_text, DEFAULT_RUSH_RELEASE_TIME_TEXT)
        self.assertEqual(state.time_range_texts, DEFAULT_RUSH_TIME_RANGES)

    def test_valid_input_is_preserved_including_row_count(self) -> None:
        state = normalize_rush_ui_state(
            "huxiaoming",
            "只要室外场",
            "3",
            "12:00:02",
            ("21:00-22:00", "19:00-20:00"),
        )
        self.assertEqual(state.venue_key, "huxiaoming")
        self.assertEqual(state.huxiaoming_court_scope, HUXIAOMING_COURT_SCOPE_OUTDOOR)
        self.assertEqual(state.court, 3)
        self.assertEqual(state.release_time_text, "12:00:02")
        self.assertEqual(state.time_range_texts, ("21:00-22:00", "19:00-20:00"))

    def test_unknown_venue_falls_back(self) -> None:
        state = normalize_rush_ui_state("somewhere-else", "只要室内场", "6")
        self.assertEqual(state.venue_key, DEFAULT_RUSH_VENUE_KEY)

    def test_non_huxiaoming_venue_forces_all_courts_scope(self) -> None:
        state = normalize_rush_ui_state("east", "只要室内场", "7")
        self.assertEqual(state.venue_key, "east")
        self.assertEqual(state.huxiaoming_court_scope, HUXIAOMING_COURT_SCOPE_ALL)
        self.assertEqual(state.court, 7)

    def test_court_outside_scope_falls_back_to_default_preferred(self) -> None:
        state = normalize_rush_ui_state("huxiaoming", "只要室内场", "3")
        self.assertEqual(state.huxiaoming_court_scope, HUXIAOMING_COURT_SCOPE_INDOOR)
        self.assertEqual(state.court, DEFAULT_RUSH_PREFERRED_COURT)

    def test_bogus_court_values_fall_back_instead_of_raising(self) -> None:
        for value in ("", "场地", "abc", "0", "9", None, True, 3.5):
            with self.subTest(value=value):
                state = normalize_rush_ui_state("east", None, value)
                self.assertEqual(state.court, DEFAULT_RUSH_PREFERRED_COURT)

    def test_bad_release_time_falls_back(self) -> None:
        for value in ("", "12:00", "25:00:00", "abc", None, 12):
            with self.subTest(value=value):
                state = normalize_rush_ui_state(None, None, None, value)
                self.assertEqual(
                    state.release_time_text,
                    DEFAULT_RUSH_RELEASE_TIME_TEXT,
                )

    def test_time_ranges_drop_invalid_and_dedupe(self) -> None:
        state = normalize_rush_ui_state(
            None,
            None,
            None,
            None,
            ("19:00-20:00", "06:00-07:00", "东西", "19:00-20:00", "21:00-22:00"),
        )
        self.assertEqual(state.time_range_texts, ("19:00-20:00", "21:00-22:00"))

    def test_time_ranges_cap_at_seven_entries(self) -> None:
        nine_ranges = tuple(
            f"{hour:02d}:00-{hour + 1:02d}:00" for hour in range(7, 16)
        )
        state = normalize_rush_ui_state(None, None, None, None, nine_ranges)
        self.assertEqual(len(state.time_range_texts), 7)
        self.assertEqual(state.time_range_texts[0], "07:00-08:00")

    def test_empty_time_ranges_fall_back_to_defaults(self) -> None:
        for value in ([], (), None, "19:00-20:00", (None, 3)):
            with self.subTest(value=value):
                state = normalize_rush_ui_state(None, None, None, None, value)
                self.assertEqual(state.time_range_texts, DEFAULT_RUSH_TIME_RANGES)

    def test_describe_labels_the_state(self) -> None:
        state = normalize_rush_ui_state(
            "huxiaoming",
            "只要室内场",
            "6",
            "12:00:00",
            ("19:00-20:00",),
        )
        self.assertEqual(
            describe_rush_ui_state(state),
            "胡晓明网球场（只要室内场） 场地6，19:00-20:00，12:00:00 开始抢场",
        )


class RushUiStateFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "rush_state.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_file_yields_defaults(self) -> None:
        state = load_rush_ui_state(self.path)
        self.assertEqual(state.time_range_texts, DEFAULT_RUSH_TIME_RANGES)
        self.assertEqual(state.venue_key, DEFAULT_RUSH_VENUE_KEY)

    def test_round_trip_preserves_every_setting(self) -> None:
        save_rush_ui_state(
            "huxiaoming",
            "只要室外场",
            "5",
            "11:59:58",
            ("20:00-21:00", "19:00-20:00", "18:00-19:00"),
            path=self.path,
        )
        state = load_rush_ui_state(self.path)
        self.assertEqual(state.venue_key, "huxiaoming")
        self.assertEqual(state.huxiaoming_court_scope, HUXIAOMING_COURT_SCOPE_OUTDOOR)
        self.assertEqual(state.court, 5)
        self.assertEqual(state.release_time_text, "11:59:58")
        self.assertEqual(
            state.time_range_texts,
            ("20:00-21:00", "19:00-20:00", "18:00-19:00"),
        )

    def test_saved_payload_never_contains_a_date(self) -> None:
        save_rush_ui_state(path=self.path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("date", payload)
        self.assertNotIn("target_date", payload)

    def test_save_normalizes_before_writing(self) -> None:
        save_rush_ui_state("nope", "只要室内场", "车队", "99", ("xx",), path=self.path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["venue_key"], DEFAULT_RUSH_VENUE_KEY)
        self.assertEqual(
            payload["huxiaoming_court_scope"],
            DEFAULT_RUSH_HUXIAOMING_COURT_SCOPE,
        )
        self.assertEqual(payload["court"], DEFAULT_RUSH_PREFERRED_COURT)
        self.assertEqual(payload["release_time"], DEFAULT_RUSH_RELEASE_TIME_TEXT)
        self.assertEqual(payload["time_ranges"], list(DEFAULT_RUSH_TIME_RANGES))

    def test_corrupt_json_yields_defaults(self) -> None:
        self.path.write_text("{ this is not json", encoding="utf-8")
        state = load_rush_ui_state(self.path)
        self.assertEqual(state.venue_key, DEFAULT_RUSH_VENUE_KEY)

    def test_non_dict_payload_yields_defaults(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        state = load_rush_ui_state(self.path)
        self.assertEqual(state.time_range_texts, DEFAULT_RUSH_TIME_RANGES)

    def test_partially_valid_file_keeps_the_good_fields(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "venue_key": "huxiaoming",
                    "huxiaoming_court_scope": "只要室外场",
                    "court": "3",
                    "release_time": "not-a-time",
                    "time_ranges": ["19:00-20:00", "bogus"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        state = load_rush_ui_state(self.path)
        self.assertEqual(state.court, 3)
        self.assertEqual(state.time_range_texts, ("19:00-20:00",))
        self.assertEqual(state.release_time_text, DEFAULT_RUSH_RELEASE_TIME_TEXT)

    def test_unwritable_target_does_not_raise(self) -> None:
        directory = Path(self._tmp.name) / "not-a-file"
        directory.mkdir()
        state = save_rush_ui_state("east", None, "2", "12:00:00", None, path=directory)
        self.assertEqual(state.venue_key, "east")


if __name__ == "__main__":
    unittest.main()
