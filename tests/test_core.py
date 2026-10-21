import unittest
from datetime import datetime, timedelta

from mini_cron_parse import next_run, CronExpression, CronField


class TestCronField(unittest.TestCase):
    def test_star_matches_all(self):
        f = CronField.parse("*", 0, 10)
        self.assertTrue(f.star)
        for i in range(11):
            self.assertTrue(f.matches(i))

    def test_single_value(self):
        f = CronField.parse("5", 0, 10)
        self.assertFalse(f.star)
        self.assertTrue(f.matches(5))
        self.assertFalse(f.matches(4))
        self.assertFalse(f.matches(6))

    def test_range(self):
        f = CronField.parse("2-5", 0, 10)
        self.assertTrue(f.matches(2))
        self.assertTrue(f.matches(5))
        self.assertFalse(f.matches(1))
        self.assertFalse(f.matches(6))

    def test_step(self):
        f = CronField.parse("*/2", 0, 10)
        expected = {0, 2, 4, 6, 8, 10}
        self.assertEqual(f.values, frozenset(expected))

    def test_range_with_step(self):
        f = CronField.parse("1-10/3", 0, 10)
        self.assertEqual(f.values, frozenset({1, 4, 7, 10}))

    def test_list(self):
        f = CronField.parse("1,3,5", 0, 10)
        self.assertEqual(f.values, frozenset({1, 3, 5}))

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            CronField.parse("60", 0, 59)
        with self.assertRaises(ValueError):
            CronField.parse("-1", 0, 59)

    def test_range_end_before_start_raises(self):
        with self.assertRaises(ValueError):
            CronField.parse("5-3", 0, 10)

    def test_step_zero_raises(self):
        with self.assertRaises(ValueError):
            CronField.parse("*/0", 0, 10)


class TestCronExpression(unittest.TestCase):
    def test_parse_five_fields(self):
        expr = CronExpression.parse("0 0 1 1 *")
        self.assertTrue(expr.minute.matches(0))
        self.assertTrue(expr.hour.matches(0))
        self.assertTrue(expr.dom.matches(1))
        self.assertTrue(expr.month.matches(1))
        self.assertTrue(expr.dow.star)

    def test_parse_wrong_field_count_raises(self):
        with self.assertRaises(ValueError):
            CronExpression.parse("0 0 * *")
        with self.assertRaises(ValueError):
            CronExpression.parse("0 0 * * * *")

    def test_sunday_both_0_and_7(self):
        # 7 should normalize to 0
        expr = CronExpression.parse("0 0 * * 7")
        # 2024-01-07 is a Sunday (weekday() == 6)
        self.assertTrue(expr.matches(datetime(2024, 1, 7, 0, 0)))

    def test_dom_and_dow_or_logic(self):
        # 0 0 1 * 0 — midnight on the 1st OR on Sunday
        expr = CronExpression.parse("0 0 1 * 0")
        # 2024-01-01 is Monday, day 1 of month → should match (dom)
        self.assertTrue(expr.matches(datetime(2024, 1, 1, 0, 0)))
        # 2024-01-07 is Sunday, day 7 → should match (dow)
        self.assertTrue(expr.matches(datetime(2024, 1, 7, 0, 0)))
        # 2024-01-02 is Tuesday, day 2 → no match
        self.assertFalse(expr.matches(datetime(2024, 1, 2, 0, 0)))

    def test_dom_star_dow_restricted(self):
        # * * * * 1 — only Mondays (cron Monday=1)
        expr = CronExpression.parse("0 0 * * 1")
        self.assertTrue(expr.matches(datetime(2024, 1, 1, 0, 0)))  # Mon
        self.assertFalse(expr.matches(datetime(2024, 1, 2, 0, 0)))  # Tue

    def test_both_star_matches_every_day(self):
        expr = CronExpression.parse("0 0 * * *")
        for day in range(1, 11):
            self.assertTrue(expr.matches(datetime(2024, 1, day, 0, 0)))


class TestNextRun(unittest.TestCase):
    def test_basic_daily(self):
        # Every day at 03:30
        result = next_run("30 3 * * *", datetime(2024, 1, 1, 0, 0))
        self.assertEqual(result, datetime(2024, 1, 1, 3, 30))

    def test_next_day_if_already_past(self):
        # 03:30 but we start at 04:00 → next day
        result = next_run("30 3 * * *", datetime(2024, 1, 1, 4, 0))
        self.assertEqual(result, datetime(2024, 1, 2, 3, 30))

    def test_strictly_after_start(self):
        # Start IS a match → should return next, not the same
        result = next_run("30 3 * * *", datetime(2024, 1, 1, 3, 30))
        self.assertEqual(result, datetime(2024, 1, 2, 3, 30))

    def test_every_minute(self):
        result = next_run("* * * * *", datetime(2024, 1, 1, 0, 0))
        self.assertEqual(result, datetime(2024, 1, 1, 0, 1))

    def test_month_boundary(self):
        # 1st of every month at midnight
        result = next_run("0 0 1 * *", datetime(2024, 1, 2, 0, 0))
        self.assertEqual(result, datetime(2024, 2, 1, 0, 0))

    def test_year_boundary(self):
        # Jan 1 at midnight, starting Dec 31
        result = next_run("0 0 1 1 *", datetime(2024, 12, 31, 23, 59))
        self.assertEqual(result, datetime(2025, 1, 1, 0, 0))

    def test_impossible_expression_raises(self):
        # Feb 31 does not exist
        with self.assertRaises(ValueError):
            next_run("0 0 31 2 *", datetime(2024, 1, 1))

    def test_step_minutes(self):
        # Every 5 minutes
        result = next_run("*/5 * * * *", datetime(2024, 1, 1, 0, 2))
        self.assertEqual(result, datetime(2024, 1, 1, 0, 5))

    def test_list_values(self):
        # At minute 0, 15, 30, 45 of every hour
        result = next_run("0,15,30,45 * * * *", datetime(2024, 1, 1, 0, 16))
        self.assertEqual(result, datetime(2024, 1, 1, 0, 30))

    def test_seconds_and_microseconds_floored(self):
        # Start has seconds/microseconds; should still return the next
        # whole-minute match.
        result = next_run("30 3 * * *", datetime(2024, 1, 1, 3, 29, 59, 999))
        self.assertEqual(result, datetime(2024, 1, 1, 3, 30))

    def test_february_29_leap_year(self):
        # Feb 29 only exists in leap years
        # Starting 2024-01-01, next Feb 29 is 2024-02-29
        result = next_run("0 0 29 2 *", datetime(2024, 1, 1))
        self.assertEqual(result, datetime(2024, 2, 29, 0, 0))

    def test_february_29_non_leap_year_skips_year(self):
        # Starting 2023-01-01 (non-leap), next Feb 29 is 2024-02-29
        result = next_run("0 0 29 2 *", datetime(2023, 1, 1))
        self.assertEqual(result, datetime(2024, 2, 29, 0, 0))

    def test_dow_restricted(self):
        # Every Sunday at noon (Sunday = 0)
        # 2024-01-01 is Monday; next Sunday is 2024-01-07
        result = next_run("0 12 * * 0", datetime(2024, 1, 1, 0, 0))
        self.assertEqual(result, datetime(2024, 1, 7, 12, 0))

    def test_dom_and_dow_or(self):
        # 1st of month OR Sunday, at 00:00
        # 2024-01-01 is the 1st (Monday) → matches via dom
        result = next_run("0 0 1 * 0", datetime(2024, 1, 1, 12, 0))
        # Next match: 2024-01-07 (Sunday) via dow
        self.assertEqual(result, datetime(2024, 1, 7, 0, 0))


if __name__ == "__main__":
    unittest.main()
