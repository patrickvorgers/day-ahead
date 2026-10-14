"""Use real SQLite predicates with the optimizer's actual forecast bounds."""

import datetime as dt
import logging
import os
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine

from dao.lib.db_manager import DBmanagerObj
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


@pytest.mark.parametrize("end_utc", [
    "2026-01-15T08:00:00+00:00", "2026-07-02T08:00:00+00:00",
    "2026-03-29T01:00:00+00:00", "2026-10-25T01:00:00+00:00",
], ids=["winter", "summer", "spring-skipped-hour", "autumn-repeated-hour"])
@pytest.mark.parametrize("interval, seconds", [("1hour", 3600), ("15min", 900)])
@pytest.mark.parametrize("extension", [0, 2], ids=["fixed-only", "with-prediction"])
def test_optimizer_bounds_select_start_and_exclude_end(monkeypatch, process_zone, end_utc, interval, seconds, extension):
    fixed_end = dt.datetime.fromisoformat(end_utc)
    start = fixed_end - dt.timedelta(seconds=8 * seconds)
    expected_start = int(start.timestamp() // 3600 * 3600)
    expected_fixed_end = int(fixed_end.timestamp())
    expected_end = expected_fixed_end + extension * 3600
    zone = ZoneInfo("Europe/Amsterdam")

    def prices(begin, count, step):
        instants = [begin + dt.timedelta(seconds=index * step) for index in range(count)]
        return pd.DataFrame({"time": [value.astimezone(zone).replace(tzinfo=None) for value in instants]})

    fixed_prices = prices(start, 8, seconds)
    predicted_prices = prices(fixed_end, extension, 3600)
    report = SimpleNamespace(get_price_data=lambda *args, extension=0, **kwargs:
                             predicted_prices.copy() if extension else fixed_prices.copy())
    monkeypatch.setattr(day_ahead, "Report", lambda *args: report)

    manager = DBmanagerObj.__new__(DBmanagerObj)
    manager.db_dialect = "sqlite"
    manager.engine = create_engine("sqlite:///:memory:")
    manager.metadata = MetaData()
    variables = Table("variabel", manager.metadata, Column("id", Integer, primary_key=True), Column("code", String))
    prognoses = Table("prognoses", manager.metadata, Column("id", Integer, primary_key=True),
                      Column("variabel", Integer), Column("time", Integer), Column("value", Float))
    manager.metadata.create_all(manager.engine)
    epochs = sorted({expected_start - 1, expected_start, expected_start + seconds,
                     expected_fixed_end - 1, expected_fixed_end, expected_fixed_end + 1,
                     expected_end - 1, expected_end, expected_end + 1})
    with manager.engine.begin() as connection:
        connection.execute(variables.insert(), [{"id": 1, "code": "temp"}, {"id": 2, "code": "gr"}])
        connection.execute(prognoses.insert(), [{"variabel": variable, "time": epoch, "value": 6.0}
                                                for epoch in epochs for variable in (1, 2)])

    queries = []
    selected_fields = []
    read_field = manager.get_prognose_field

    def observe_field(*args, **kwargs):
        result = read_field(*args, **kwargs)
        selected_fields.append([int(value) for value in result["time"]])
        return result

    monkeypatch.setattr(manager, "get_prognose_field", observe_field)
    read_forecasts = manager.get_prognose_data

    class StopAfterSelection(Exception):
        pass

    def select_forecasts(start, end, interval):
        selected_fields.clear()
        result = read_forecasts(start, end, interval)
        selected = selected_fields.copy() if interval == "15min" else [[int(value) for value in result["time"]]]
        queries.append((start, end, selected))
        if len(queries) == (2 if extension else 1):
            raise StopAfterSelection
        return result

    monkeypatch.setattr(manager, "get_prognose_data", select_forecasts)
    calculator = day_ahead.DaCalc.__new__(day_ahead.DaCalc)
    calculator.debug = False
    calculator.time_zone = "Europe/Amsterdam"
    calculator.interval = interval
    calculator.interval_s = seconds
    calculator.log_level = logging.INFO
    calculator.file_name = "unused.json"
    calculator.config = SimpleNamespace(prices=SimpleNamespace(prediction=SimpleNamespace(extension=extension)))
    calculator.db_da = manager
    try:
        with pytest.raises(StopAfterSelection):
            calculator.calc_optimum(_start_dt=start)
    finally:
        manager.engine.dispose()

    expected_bounds = [(expected_start, expected_fixed_end)]
    if extension:
        expected_bounds.append((expected_fixed_end, expected_end))
    for (begin, end, selected), (expected_begin, expected_stop) in zip(queries, expected_bounds, strict=True):
        expected = [epoch for epoch in epochs if expected_begin <= epoch < expected_stop]
        assert selected and all(rows == expected for rows in selected)
        assert all(begin <= epoch < end for rows in selected for epoch in rows)
    assert [(begin, end) for begin, end, _ in queries] == expected_bounds
