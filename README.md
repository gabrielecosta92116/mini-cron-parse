# mini-cron-parse

A small library for parsing cron expressions and finding when the next scheduled run occurs after a given datetime.

```python
from datetime import datetime
from mini_cron_parse import next_run

# Every day at 03:30
result = next_run("30 3 * * *", datetime(2024, 1, 1, 0, 0))
print(result)  # 2024-01-01 03:30:00
```

## Why this exists

Most cron parsers are embedded in large scheduling frameworks. This library does only one thing: given a 5-field cron expression and a starting `datetime`, return the next matching `datetime`. It does not execute anything, persist state, or manage timezones. The caller controls both the clock and the timezone by passing in a tz-aware or naive datetime; the library returns one of the same type.

## Interpretation decisions

- **6-field expressions are not supported.** Only the traditional 5-field form: minute, hour, day-of-month, month, day-of-week. Seconds and years are out of scope.
- **Sunday is 0.** Day-of-week values are 0-6 where 0 and 7 both mean Sunday.
- **Day-of-week and day-of-month are OR'd.** This matches traditional Vixie cron semantics: if both are restricted (not `*`), a match on either field triggers. When both are `*`, every day matches.
- **Non-standard syntax is rejected.** No `L`, `W`, `#`, `?`, or named days/months. Accepting them would require guessing at semantics that vary across implementations.

## Edge cases

- If the input datetime is itself a match, the returned time is the *next* match strictly after it.
- The search is bounded at 4 years from the start time; if no match is found in that window (e.g., `0 0 31 2 *` with no Feb 31), `ValueError` is raised.
- Leap seconds, DST transitions, and other timezone subtleties are the caller's responsibility. The library does naive arithmetic on the components you provide and hands back a datetime of the same type.
