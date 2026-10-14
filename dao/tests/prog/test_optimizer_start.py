"""Verify real optimizer entry conversions before external data is requested."""

import datetime as dt
import inspect
import logging
import os
import time

import pytest

from dao.prog import day_ahead

pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="Process timezone tests require POSIX tzset")


@pytest.fixture(params=["UTC", "Europe/Amsterdam"])
def process_zone(request):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize(
    "reference, expected_utc, expected_local",
    [
        (dt.datetime(2026, 1, 14, 9, 14, 10), dt.datetime(2026, 1, 14, 8, 15, tzinfo=dt.UTC), dt.datetime(2026, 1, 14, 9, 15)),
        (dt.datetime(2026, 1, 14, 8, 14, 10, tzinfo=dt.UTC), dt.datetime(2026, 1, 14, 8, 15, tzinfo=dt.UTC), dt.datetime(2026, 1, 14, 9, 15)),
        (dt.datetime(2026, 10, 25, 2, 30, fold=0), dt.datetime(2026, 10, 25, 0, 30, tzinfo=dt.UTC), dt.datetime(2026, 10, 25, 2, 30, fold=0)),
        (dt.datetime(2026, 10, 25, 2, 30, fold=1), dt.datetime(2026, 10, 25, 1, 30, tzinfo=dt.UTC), dt.datetime(2026, 10, 25, 2, 30, fold=1)),
    ],
    ids=["naive-ha-reference-rounding", "aware-utc-reference-rounding", "first-repeated-minute", "second-repeated-minute"],
)
def test_reference_start_and_interval_keep_physical_identity(monkeypatch, process_zone, reference, expected_utc, expected_local):
    observed = {}

    class StopBeforeExternalData(Exception):
        pass

    def stop_at_report(*args):
        # Observe the real entry path, then stop before database/model work.
        values = inspect.currentframe().f_back.f_locals
        observed.update({key: values[key] for key in ("start_ts", "start_dt", "start_interval_ts", "start_interval_dt")})
        raise StopBeforeExternalData

    monkeypatch.setattr(day_ahead, "Report", stop_at_report)
    calculator = day_ahead.DaCalc.__new__(day_ahead.DaCalc)
    calculator.debug = False
    calculator.time_zone = "Europe/Amsterdam"
    calculator.interval_s = 900
    calculator.log_level = logging.INFO
    calculator.file_name = "unused.json"

    with pytest.raises(StopBeforeExternalData):
        calculator.calc_optimum(_start_dt=reference)

    assert observed["start_ts"] == expected_utc.timestamp()
    assert observed["start_interval_ts"] == expected_utc.timestamp()
    for key in ("start_dt", "start_interval_dt"):
        assert observed[key] == expected_local
        assert observed[key].fold == expected_local.fold
