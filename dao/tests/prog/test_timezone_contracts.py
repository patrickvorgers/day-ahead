"""Run identical HA inputs under two process zones, without live services."""

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[3]
HA_ZONE = "Europe/Amsterdam"
CASES = [
    ("winter", "2026-01-14T08:00:00+00:00", "2026-01-14 12:00:00"),
    ("summer", "2026-07-01T08:00:00+00:00", "2026-07-01 13:00:00"),
    ("local-midnight", "2026-07-01T22:30:00+00:00", "2026-07-02 03:30:00"),
    ("spring-forward", "2026-03-29T00:30:00+00:00", "2026-03-29 03:30:00"),
    ("fall-back", "2026-10-24T23:30:00+00:00", "2026-10-25 03:30:00"),
    ("first-0230", "2026-10-25T00:30:00+00:00", "2026-10-25 03:30:00"),
    ("second-0230", "2026-10-25T01:30:00+00:00", "2026-10-25 03:30:00"),
]
pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="Application subprocess TZ matrix requires POSIX tzset")


@pytest.fixture(scope="module", params=CASES, ids=[case[0] for case in CASES])
def matrix(request):
    name, instant, ready = request.param
    rows = {}
    for zone in ("UTC", HA_ZONE):
        environment = {**os.environ, "TZ": zone, "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "dao/prog")))}
        payload = {"instant": instant, "ready": ready, "ha_zone": HA_ZONE}
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tests/timezone_probe.py"), json.dumps(payload)],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stdout[-4000:] + completed.stderr[-4000:])
        rows[zone] = json.loads(next(line.removeprefix("TIMEZONE_RESULT=")
                                    for line in completed.stdout.splitlines() if line.startswith("TIMEZONE_RESULT=")))
        if rows[zone]["process_zone"] != zone:
            raise RuntimeError("The subprocess did not preserve its requested process timezone")
    if rows["UTC"]["planning"]["input_digest"] != rows[HA_ZONE]["planning"]["input_digest"]:
        raise RuntimeError("The subprocesses did not receive identical canonical planning inputs")
    return name, payload, rows


def test_report_periods_are_process_zone_independent(matrix):
    _, _, rows = matrix
    assert rows["UTC"]["periods"] == rows[HA_ZONE]["periods"]


def test_today_uses_ha_midnight_and_real_day_length(matrix):
    _, payload, rows = matrix
    local = dt.datetime.fromisoformat(payload["instant"]).astimezone(ZoneInfo(HA_ZONE))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
    end = start + dt.timedelta(days=1)
    expected = [int(start.timestamp()), int(end.timestamp())]
    for row in rows.values():
        assert row["periods"]["vandaag"] == expected


def test_scheduler_dispatch_uses_ha_clock(matrix):
    _, _, rows = matrix
    for row in rows.values():
        assert row["dispatched"] == ["calculate"]


def test_price_requests_are_process_zone_independent(matrix):
    _, _, rows = matrix
    assert rows["UTC"]["price_bounds"] == rows[HA_ZONE]["price_bounds"]


def test_price_request_covers_local_calendar_days(matrix):
    _, payload, rows = matrix
    local = dt.datetime.fromisoformat(payload["instant"]).astimezone(ZoneInfo(HA_ZONE))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
    end = start + dt.timedelta(days=1 if local.hour < 12 else 2)
    for row in rows.values():
        assert row["price_bounds"] == [int(start.timestamp()), int(end.timestamp())]


def test_available_charging_hours_are_elapsed_hours(matrix):
    _, payload, rows = matrix
    instant = dt.datetime.fromisoformat(payload["instant"])
    ready = dt.datetime.fromisoformat(payload["ready"]).replace(tzinfo=ZoneInfo(HA_ZONE))
    expected = (ready.timestamp() - instant.timestamp()) / 3600
    for row in rows.values():
        assert "available_hours" in row["planning"], row["planning"]
        assert row["planning"]["available_hours"] == pytest.approx(expected)


def test_optimizer_start_epoch_is_process_zone_independent(matrix):
    """Pin the correct physical start separately from the broken clock label."""
    _, payload, rows = matrix
    instant = dt.datetime.fromisoformat(payload["instant"])
    expected_epoch = int(instant.timestamp())
    for row in rows.values():
        clock = row["planning"]["start_calendar"]
        assert clock["start_epoch"] == expected_epoch
        # All anchors lie on quarter-hour boundaries, so no rounding is needed.
        assert clock["interval_epoch"] == expected_epoch


def test_optimizer_start_calendar_uses_ha_zone(matrix):
    """The first epoch-to-calendar conversion must respect the HA clock."""
    _, payload, rows = matrix
    instant = dt.datetime.fromisoformat(payload["instant"])
    expected = instant.astimezone(ZoneInfo(HA_ZONE)).replace(tzinfo=None)
    for row in rows.values():
        clock = row["planning"]["start_calendar"]
        for key in ("start_label", "interval_label"):
            label = dt.datetime.fromisoformat(clock[key])
            if label.utcoffset() is not None:
                assert label.timestamp() == instant.timestamp(), clock
            assert label.replace(tzinfo=None) == expected, clock


def test_actual_optimizer_plan_is_process_zone_independent(matrix):
    _, payload, rows = matrix
    epoch = int(dt.datetime.fromisoformat(payload["instant"]).timestamp())
    for row in rows.values():
        assert row["planning"]["solved"], row["planning"]
        assert row["planning"]["start_epoch"] == epoch
        assert row["planning"]["plan"]
    assert rows["UTC"]["planning"]["plan"] == rows[HA_ZONE]["planning"]["plan"]
    assert rows["UTC"]["planning"]["objective"] == pytest.approx(rows[HA_ZONE]["planning"]["objective"])
