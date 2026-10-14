"""Check schedule matching without waiting or starting application processes."""

import datetime as dt
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from dao.prog import da_scheduler


class EndSchedulerIteration(Exception):
    """Stop the infinite scheduler after one complete dispatch iteration."""


@pytest.mark.parametrize("schedule,expected", [
    ({"0215": "exact"}, ["exact"]),
    ({"xx15": "minute"}, ["minute"]),
    ({"02xx": "hour"}, ["hour"]),
    ({"0214": "exact", "xx14": "minute", "03xx": "hour"}, []),
    ({"02xx": "hour", "0215": "exact", "xx15": "minute"}, ["hour", "exact", "minute"]),
    ({"0215": "exact", "xx15": "exact", "02xx": "exact"}, ["exact", "exact", "exact"]),
])
def test_schedule_patterns_preserve_dispatch_order_and_multiplicity(monkeypatch, schedule, expected):
    scheduler = da_scheduler.DaScheduler.__new__(da_scheduler.DaScheduler)
    scheduler.active = True
    scheduler.offset_start = 0
    scheduler.time_zone = "Europe/Amsterdam"
    scheduler.scheduler_tasks = schedule
    scheduler.tasks = {name: {"function": name} for name in ("exact", "minute", "hour")}
    scheduler.run_task_process = Mock(return_value=True)
    clock = Mock()
    clock.now.side_effect = [dt.datetime(2026, 1, 14, 1, 14, tzinfo=dt.UTC),
                             dt.datetime(2026, 1, 14, 1, 15, tzinfo=dt.UTC), EndSchedulerIteration()]
    monkeypatch.setattr(da_scheduler, "datetime", SimpleNamespace(datetime=clock, timedelta=dt.timedelta, UTC=dt.UTC))
    monkeypatch.setattr(da_scheduler, "time", SimpleNamespace(sleep=Mock()))

    with pytest.raises(EndSchedulerIteration):
        scheduler.scheduler()

    assert [call.args[0] for call in scheduler.run_task_process.call_args_list] == expected


@pytest.fixture
def run_clock(monkeypatch):
    def run(start, end, schedule, offset=0, block_seconds=0, early_wake=False, active=True):
        epoch = start.timestamp()
        calls = []
        wake_count = 0

        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromtimestamp(epoch, tz)

        def sleep(seconds):
            nonlocal epoch, wake_count
            assert seconds >= 0
            wake_count += 1
            if wake_count > 1000:
                pytest.fail("Scheduler did not advance")
            if not (early_wake and wake_count == 1):
                epoch += seconds
            if epoch + offset >= end.timestamp():
                raise EndSchedulerIteration

        def execute(task):
            nonlocal epoch
            calls.append((task, epoch))
            epoch += block_seconds

        scheduler = da_scheduler.DaScheduler.__new__(da_scheduler.DaScheduler)
        scheduler.active = active
        scheduler.offset_start = offset
        scheduler.time_zone = "Europe/Amsterdam"
        scheduler.scheduler_tasks = schedule
        scheduler.tasks = {task: {"function": task} for task in schedule.values()}
        scheduler.run_task_process = execute
        monkeypatch.setattr(da_scheduler, "datetime", SimpleNamespace(datetime=Clock, timedelta=dt.timedelta, UTC=dt.UTC))
        monkeypatch.setattr(da_scheduler, "time", SimpleNamespace(sleep=sleep))
        with pytest.raises(EndSchedulerIteration):
            scheduler.scheduler()
        return calls

    return run


@pytest.fixture(params=["UTC", "Europe/Amsterdam"])
def process_zone(request):
    if not hasattr(time, "tzset"):
        pytest.skip("Process timezone verification requires POSIX tzset")
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


@pytest.mark.parametrize("day, exact_count", [("2026-03-29", 0), ("2026-10-25", 2)])
@pytest.mark.parametrize("offset", [0, 10, 60])
def test_continuous_dst_minutes_and_elapsed_offsets(run_clock, process_zone, day, exact_count, offset, caplog):
    start = dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC)
    end = start.replace(hour=2, second=0)
    schedule = {f"xx{minute:02}": "tick" for minute in range(60)}
    schedule["0230"] = "exact"
    with caplog.at_level("DEBUG", logger=da_scheduler.__name__):
        calls = run_clock(start, end, schedule, offset=offset)

    # Enumerate physical instants independently of the scheduler's local clock.
    expected = [int(start.replace(second=0).timestamp()) + minute * 60 for minute in range(1, 120)]
    ticks = [epoch + offset for task, epoch in calls if task == "tick"]
    assert ticks == expected
    exact = [epoch + offset for task, epoch in calls if task == "exact"]
    assert len(exact) == exact_count
    if exact_count:
        assert exact[1] - exact[0] == 3600
        labels = [dt.datetime.fromtimestamp(epoch, ZoneInfo("Europe/Amsterdam")).isoformat() for epoch in exact]
        assert labels == ["2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"]
        assert all(label.replace("T", " ") in caplog.text for label in labels)


def test_same_physical_minute_is_not_dispatched_twice(run_clock):
    start = dt.datetime(2026, 1, 14, 0, 29, 50, tzinfo=dt.UTC)
    calls = run_clock(start, start.replace(minute=31, second=0), {"xx30": "tick"}, early_wake=True)
    assert [task for task, _ in calls] == ["tick"]


def test_blocking_task_does_not_catch_up_missed_minutes(run_clock):
    start = dt.datetime(2026, 1, 14, 0, 0, 1, tzinfo=dt.UTC)
    calls = run_clock(start, start.replace(minute=6, second=0), {f"xx{minute:02}": "tick" for minute in range(60)}, block_seconds=180)
    assert [epoch - start.replace(second=0).timestamp() for _, epoch in calls] == [60, 300]


def test_inactive_scheduler_does_not_dispatch(run_clock):
    start = dt.datetime(2026, 1, 14, 0, 0, 1, tzinfo=dt.UTC)
    assert run_clock(start, start.replace(minute=3, second=0), {"xx01": "tick"}, active=False) == []
