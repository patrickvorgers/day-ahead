"""Verify provider calendar bounds without contacting a price service."""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dao.lib import da_prices


@pytest.fixture
def request_prices(monkeypatch):
    def request(instant, zone="Europe/Amsterdam", start=None, end=None):
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                # Model a UTC process; a supplied timezone determines its clock.
                return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

        monkeypatch.setattr(da_prices, "datetime", SimpleNamespace(datetime=Clock, timedelta=dt.timedelta))
        provider = Mock()
        provider.query_day_ahead_prices.return_value = pd.DataFrame()
        monkeypatch.setattr(da_prices, "EntsoePandasClient", Mock(return_value=provider))
        database = Mock()
        database.get_time_border_record.return_value = None
        config = SimpleNamespace(interval="1hour", prices=SimpleNamespace(entsoe_api_key=None))
        da_prices.DaPrices(config, database, time_zone=zone).get_prices("entsoe", start, end)
        return provider.query_day_ahead_prices.call_args.kwargs

    return request


@pytest.mark.parametrize(
    "instant, start_utc, end_utc, hours",
    [
        ("2026-03-29T07:00:00+00:00", "2026-03-28T23:00:00+00:00", "2026-03-29T22:00:00+00:00", 23),
        ("2026-10-25T08:00:00+00:00", "2026-10-24T22:00:00+00:00", "2026-10-25T23:00:00+00:00", 25),
        ("2026-03-28T12:00:00+00:00", "2026-03-27T23:00:00+00:00", "2026-03-29T22:00:00+00:00", 47),
        ("2026-10-24T12:00:00+00:00", "2026-10-23T22:00:00+00:00", "2026-10-25T23:00:00+00:00", 49),
        ("2026-07-01T22:30:00+00:00", "2026-07-01T22:00:00+00:00", "2026-07-02T22:00:00+00:00", 24),
        ("2026-07-01T09:59:00+00:00", "2026-06-30T22:00:00+00:00", "2026-07-01T22:00:00+00:00", 24),
        ("2026-07-01T10:00:00+00:00", "2026-06-30T22:00:00+00:00", "2026-07-02T22:00:00+00:00", 48),
    ],
    ids=["spring-23h", "autumn-25h", "spring-two-days-47h", "autumn-two-days-49h", "ha-midnight", "before-ha-noon", "at-ha-noon"],
)
def test_entsoe_query_covers_ha_calendar_days(request_prices, instant, start_utc, end_utc, hours):
    query = request_prices(dt.datetime.fromisoformat(instant))

    assert query["start"].timestamp() == dt.datetime.fromisoformat(start_utc).timestamp()
    assert query["end"].timestamp() == dt.datetime.fromisoformat(end_utc).timestamp()
    assert (query["end"].timestamp() - query["start"].timestamp()) / 3600 == hours


def test_entsoe_uses_configured_zone_instead_of_cet(request_prices):
    query = request_prices(dt.datetime(2026, 7, 1, 22, 30, tzinfo=dt.UTC), zone="Europe/London")

    assert query["start"].timestamp() == dt.datetime(2026, 6, 30, 23, tzinfo=dt.UTC).timestamp()
    assert query["end"].timestamp() == dt.datetime(2026, 7, 2, 23, tzinfo=dt.UTC).timestamp()


@pytest.mark.parametrize("aware", [False, True], ids=["naive-ha-local", "aware-utc"])
def test_explicit_bounds_retain_local_calendar_day_contract(request_prices, aware):
    start = dt.datetime(2026, 10, 25, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
    end = dt.datetime(2026, 10, 26, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
    if aware:
        start, end = start.astimezone(dt.UTC), end.astimezone(dt.UTC)
    else:
        start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    query = request_prices(dt.datetime(2026, 10, 25, 8, tzinfo=dt.UTC), start=start, end=end)

    assert query["start"].timestamp() == dt.datetime(2026, 10, 24, 22, tzinfo=dt.UTC).timestamp()
    assert query["end"].timestamp() == dt.datetime(2026, 10, 25, 23, tzinfo=dt.UTC).timestamp()
