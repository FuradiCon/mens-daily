import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from record_traffic import merge_days, parse_days, read_envelope, write_envelope

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "goatcounter_stats_total.json"


class ParseDaysTest(unittest.TestCase):
    """Parsing is asserted against a real recorded API response, not a guessed schema."""

    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_extracts_one_row_per_day(self):
        rows = parse_days(self.payload)
        self.assertEqual(len(rows), len(self.payload["stats"]))

    def test_rows_have_only_date_and_views(self):
        for row in parse_days(self.payload):
            self.assertEqual(set(row), {"d", "views"})

    def test_reads_the_daily_field_not_hourly(self):
        rows = {r["d"]: r["views"] for r in parse_days(self.payload)}
        for stat in self.payload["stats"]:
            self.assertEqual(rows[stat["day"]], stat["daily"])

    def test_recorded_test_pageview_survives_parsing(self):
        # the fixture captured exactly one real pageview on 2026-07-29
        rows = {r["d"]: r["views"] for r in parse_days(self.payload)}
        self.assertEqual(rows["2026-07-29"], 1)

    def test_missing_stats_key_yields_no_rows(self):
        self.assertEqual(parse_days({}), [])


class MergeDaysTest(unittest.TestCase):
    def test_adds_a_new_day(self):
        existing = [{"d": "2026-07-01", "views": 5}]
        merged = merge_days(existing, [{"d": "2026-07-02", "views": 3}], keep_days=180)
        self.assertEqual(merged, [
            {"d": "2026-07-01", "views": 5},
            {"d": "2026-07-02", "views": 3},
        ])

    def test_refetching_a_day_overwrites_rather_than_duplicates(self):
        existing = [{"d": "2026-07-01", "views": 5}]
        merged = merge_days(existing, [{"d": "2026-07-01", "views": 9}], keep_days=180)
        self.assertEqual(merged, [{"d": "2026-07-01", "views": 9}])

    def test_backfills_a_gap_left_by_a_skipped_run(self):
        existing = [{"d": "2026-07-01", "views": 5}]
        incoming = [{"d": "2026-07-02", "views": 1}, {"d": "2026-07-03", "views": 2}]
        merged = merge_days(existing, incoming, keep_days=180)
        self.assertEqual([r["d"] for r in merged], ["2026-07-01", "2026-07-02", "2026-07-03"])

    def test_output_is_sorted_by_date(self):
        merged = merge_days(
            [{"d": "2026-07-03", "views": 1}],
            [{"d": "2026-07-01", "views": 2}],
            keep_days=180,
        )
        self.assertEqual([r["d"] for r in merged], ["2026-07-01", "2026-07-03"])

    def test_trim_keeps_the_most_recent_days(self):
        existing = [{"d": f"2026-07-{n:02d}", "views": n} for n in range(1, 11)]
        merged = merge_days(existing, [], keep_days=3)
        self.assertEqual([r["d"] for r in merged], ["2026-07-08", "2026-07-09", "2026-07-10"])


class EnvelopeTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parent / "_tmp_traffic.json"
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))

    def test_round_trips_days(self):
        write_envelope(self.path, [{"d": "2026-07-01", "views": 4}], fetched_at="2026-07-01T00:00:00Z")
        self.assertEqual(read_envelope(self.path)["days"], [{"d": "2026-07-01", "views": 4}])

    def test_success_stamps_fetched_at_and_clears_error(self):
        write_envelope(self.path, [], fetched_at="2026-07-01T00:00:00Z")
        envelope = read_envelope(self.path)
        self.assertEqual(envelope["fetched_at"], "2026-07-01T00:00:00Z")
        self.assertIsNone(envelope["last_error"])

    def test_failure_records_error_and_preserves_existing_days(self):
        write_envelope(self.path, [{"d": "2026-07-01", "views": 4}], fetched_at="2026-07-01T00:00:00Z")
        existing = read_envelope(self.path)
        write_envelope(
            self.path,
            existing["days"],
            fetched_at=existing["fetched_at"],
            last_error="HTTP 500 from GoatCounter",
        )
        envelope = read_envelope(self.path)
        self.assertEqual(envelope["days"], [{"d": "2026-07-01", "views": 4}])
        self.assertEqual(envelope["last_error"], "HTTP 500 from GoatCounter")
        self.assertEqual(envelope["fetched_at"], "2026-07-01T00:00:00Z")

    def test_missing_file_reads_as_empty_envelope(self):
        envelope = read_envelope(self.path)
        self.assertEqual(envelope["days"], [])
        self.assertIsNone(envelope["fetched_at"])

    def test_legacy_bare_array_is_read_as_days(self):
        # traffic.json was a top-level array before this change
        self.path.write_text(json.dumps([{"d": "2026-07-01", "views": 0, "uniques": 0}]), encoding="utf-8")
        self.assertEqual(read_envelope(self.path)["days"], [{"d": "2026-07-01", "views": 0, "uniques": 0}])


if __name__ == "__main__":
    unittest.main()
