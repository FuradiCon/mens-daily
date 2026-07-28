import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_daily import already_published_today


class AlreadyPublishedTodayTest(unittest.TestCase):
    def test_true_when_entry_matches_today(self):
        self.assertTrue(already_published_today({"date": "2026-07-28"}, "2026-07-28"))

    def test_false_when_entry_is_a_different_day(self):
        self.assertFalse(already_published_today({"date": "2026-07-27"}, "2026-07-28"))

    def test_false_when_no_entry_exists(self):
        self.assertFalse(already_published_today(None, "2026-07-28"))

    def test_false_when_entry_has_no_date_field(self):
        self.assertFalse(already_published_today({}, "2026-07-28"))


if __name__ == "__main__":
    unittest.main()
