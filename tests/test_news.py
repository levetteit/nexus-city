from datetime import datetime, timedelta

from backend.news import ET, NewsCalendar, NewsEvent

CPI = NewsEvent(datetime(2026, 10, 14, 8, 30, tzinfo=ET), "CPI m/m")
FOMC = NewsEvent(datetime(2026, 10, 28, 14, 0, tzinfo=ET), "FOMC Statement")


def test_blackout_windows():
    cal = NewsCalendar([CPI, FOMC])
    assert cal.blackout(CPI.time - timedelta(minutes=11)) is None
    assert cal.blackout(CPI.time - timedelta(minutes=10)) == CPI
    assert cal.blackout(CPI.time + timedelta(minutes=14)) == CPI
    assert cal.blackout(CPI.time + timedelta(minutes=15)) is None
    assert cal.blackout(FOMC.time + timedelta(minutes=44)) == FOMC   # FOMC runs 45 minutes after


def test_flatten_two_minutes_before():
    cal = NewsCalendar([CPI])
    assert cal.flatten_for(CPI.time - timedelta(minutes=3)) is None
    assert cal.flatten_for(CPI.time - timedelta(minutes=2)) == CPI
    assert cal.flatten_for(CPI.time) is None


def test_feed_parsing_keeps_only_high_impact_usd():
    raw = [{"title": "CPI m/m", "country": "USD", "impact": "High", "date": "2026-10-14T08:30:00-04:00"},
           {"title": "GDP", "country": "EUR", "impact": "High", "date": "2026-10-14T05:00:00-04:00"},
           {"title": "Claims", "country": "USD", "impact": "Medium", "date": "2026-10-15T08:30:00-04:00"}]
    assert [e.title for e in NewsCalendar.parse(raw)] == ["CPI m/m"]
