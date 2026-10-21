from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List


def _parse_int(value: str) -> int:
    """Parse an integer, providing a clear error message on failure."""
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Invalid integer in cron field: {value!r}") from None


@dataclass(frozen=True)
class CronField:
    """Represents a single field of a cron expression.

    A field is either a star (matches everything) or a set of allowed
    integer values within the field's range.
    """

    star: bool
    values: frozenset[int]

    @staticmethod
    def parse(expr: str, min_val: int, max_val: int) -> "CronField":
        """Parse one cron field string into a CronField.

        Supports: '*', 'N', 'N-M', 'N-M/S', '*/S', 'A,B,C'.
        Anything else raises ValueError.
        """
        s = expr.strip()
        if s == "*":
            return CronField(star=True, values=frozenset())

        if "," in s:
            parts: List[int] = []
            for part in s.split(","):
                sub = CronField.parse(part, min_val, max_val)
                if sub.star:
                    parts.extend(range(min_val, max_val + 1))
                else:
                    parts.extend(sub.values)
            return CronField(star=False, values=frozenset(parts))

        step = 1
        if "/" in s:
            base, step_str = s.split("/", 1)
            step = _parse_int(step_str)
            if step <= 0:
                raise ValueError(f"Step must be positive, got {step}")
            s = base

        if s == "*":
            start, end = min_val, max_val
        elif "-" in s:
            low_str, high_str = s.split("-", 1)
            start = _parse_int(low_str)
            end = _parse_int(high_str)
        else:
            start = _parse_int(s)
            end = start

        # Validate values against the field's range.
        if start < min_val or start > max_val:
            raise ValueError(
                f"Value {start} out of range [{min_val}, {max_val}]"
            )
        if end < min_val or end > max_val:
            raise ValueError(
                f"Value {end} out of range [{min_val}, {max_val}]"
            )
        if end < start:
            raise ValueError(
                f"Range end {end} is less than start {start}"
            )

        # For ranges with a step, the start point is fixed and we
        # count up by step. This matches Vixie cron semantics where
        # '1-10/3' yields {1, 4, 7, 10}.
        vals: List[int] = []
        val = start
        while val <= end:
            vals.append(val)
            val += step
        return CronField(star=False, values=frozenset(vals))

    def matches(self, value: int) -> bool:
        """Check whether a given value is accepted by this field."""
        if self.star:
            return True
        return value in self.values


@dataclass(frozen=True)
class CronExpression:
    """A parsed 5-field cron expression."""

    minute: CronField
    hour: CronField
    dom: CronField
    month: CronField
    dow: CronField

    @staticmethod
    def parse(expr: str) -> "CronExpression":
        """Parse a cron expression string.

        Accepts exactly 5 whitespace-separated fields:
        minute hour day-of-month month day-of-week.
        """
        if not isinstance(expr, str):
            raise TypeError("Cron expression must be a string")
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError(
                f"Expected 5 fields, got {len(fields)}"
            )
        # Day-of-week allows both 0 and 7 to represent Sunday.
        # We normalize 7 to 0 so matching is consistent.
        dow_field = CronField.parse(fields[4], 0, 7)
        if not dow_field.star:
            dow_values = frozenset(0 if v == 7 else v for v in dow_field.values)
            dow_field = CronField(star=False, values=dow_values)
        return CronExpression(
            minute=CronField.parse(fields[0], 0, 59),
            hour=CronField.parse(fields[1], 0, 23),
            dom=CronField.parse(fields[2], 1, 31),
            month=CronField.parse(fields[3], 1, 12),
            dow=dow_field,
        )

    def matches(self, dt: datetime) -> bool:
        """Check whether this expression matches the given datetime."""
        if not self.month.matches(dt.month):
            return False
        # Vixie cron semantics: when both dom and dow are restricted,
        # a match on EITHER field is sufficient. When one is '*', we
        # require a match on the other.
        dom_match = self.dom.matches(dt.day)
        # cron: Sunday=0..Saturday=6; Python: Monday=0..Sunday=6.
        cron_dow = (dt.weekday() + 1) % 7
        dow_match = self.dow.matches(cron_dow)
        if self.dom.star and self.dow.star:
            day_ok = True
        elif self.dom.star:
            day_ok = dow_match
        elif self.dow.star:
            day_ok = dom_match
        else:
            day_ok = dom_match or dow_match
        if not day_ok:
            return False
        if not self.hour.matches(dt.hour):
            return False
        if not self.minute.matches(dt.minute):
            return False
        return True


def next_run(expr: str, start: datetime) -> datetime:
    """Find the next datetime after `start` that matches the cron expression.

    If `start` itself matches, the returned time is strictly *after* it.
    The returned datetime has the same tzinfo as `start` (which may be None).
    """
    return CronExpression.parse(expr).next_after(start)


def _add_minute(dt: datetime) -> datetime:
    """Advance a datetime by one minute.

    We round down to the start of the current minute first, then add 60
    seconds. This handles the case where `start` has non-zero seconds/microseconds:
    `12:34:45` becomes `12:34:00`, then `12:35:00`.
    """
    floored = dt.replace(second=0, microsecond=0)
    return floored + timedelta(minutes=1)


# --- Search logic ---
#
# Strategy: start from the minute after `start`, then increment minute by
# minute until a match is found. To avoid pathological loops on impossible
# expressions (e.g. Feb 31), we bail out after 4 years of minutes.
#
# This is intentionally simple rather than clever: we could skip forward
# by hours or days when the month doesn't match, but the linear scan is
# easy to verify and fast enough for any realistic cron expression.
# The 4-year bound covers the longest real cycle (leap year + month/day).

_MAX_ITERATIONS = 4 * 366 * 24 * 60  # ~4 years in minutes


def _next_after(self: CronExpression, start: datetime) -> datetime:
    candidate = _add_minute(start)
    for _ in range(_MAX_ITERATIONS):
        if self.matches(candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(
        "No matching time found within 4 years; "
        "the expression may be impossible (e.g. '0 0 31 2 *')."
    )


# Attach the method to CronExpression so callers can use either
# `next_run(expr, dt)` or `CronExpression.parse(expr).next_after(dt)`.
CronExpression.next_after = _next_after  # type: ignore[attr-defined]
