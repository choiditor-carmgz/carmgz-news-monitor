"""Korean civil-time schedules, independent of the runner's timezone."""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), 'Asia/Seoul')
UTC = timezone.utc


def slots(start, end):
    """All scheduled slots in (start, end], including across UTC date changes."""
    day = start.astimezone(KST).date()
    last = end.astimezone(KST).date()
    result = []
    while day <= last:
        weekday = day.weekday() < 5
        hours = (0, 8, 10, 12, 14, 16, 18, 20, 22) if weekday else (9, 15, 21)
        times = [('collect', h, 0) for h in hours]
        times += [('pm', 17, 0)]
        if weekday:
            times += [('am', 9, 0)]
        for kind, hour, minute in times:
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST).astimezone(UTC)
            if start < at <= end:
                result.append((at, kind))
        day += timedelta(days=1)
    return sorted(result)
