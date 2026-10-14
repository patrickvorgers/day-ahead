"""Check real EV capacity limiting on a physical clock, without device writes."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="Subprocess timezone tests require POSIX tzset")


@pytest.mark.parametrize(
    "instant, ready, instant_charge, expected_hours",
    [
        ("2026-03-29T00:30:00+00:00", "2026-03-29 03:30:00", False, 1),
        ("2026-10-24T23:30:00+00:00", "2026-10-25 03:30:00", False, 3),
        ("2026-10-25T00:30:00+00:00", "2026-10-25 03:30:00", False, 2),
        ("2026-10-25T01:30:00+00:00", "2026-10-25 03:30:00", False, 1),
        ("2026-01-14T08:00:00+00:00", "2026-01-14 08:00:00", False, 0),
        ("2026-01-14T08:00:00+00:00", "2026-01-14 12:00:00", False, 3),
        ("2026-03-29T00:30:00+00:00", "2026-03-28 03:30:00", True, 24),
        ("2026-10-24T23:30:00+00:00", "2026-10-24 03:30:00", True, 24),
    ],
    ids=["spring-1h", "autumn-3h", "first-0230-2h", "second-0230-1h", "expired-deadline", "winter-control", "instant-spring-horizon", "instant-autumn-horizon"],
)
def test_elapsed_hours_limit_actual_ev_energy_and_target(instant, ready, instant_charge, expected_hours):
    rows = []
    for zone in ("UTC", "Europe/Amsterdam"):
        request = {"instant": instant, "ready": ready, "ha_zone": "Europe/Amsterdam",
                   "instant_charge": instant_charge, "wished_level": 100.0, "budget_only": True}
        environment = {**os.environ, "TZ": zone, "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "dao/prog")))}
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tests/timezone_probe.py"), json.dumps(request)],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
        )
        assert completed.returncode == 0, completed.stdout[-3000:] + completed.stderr[-3000:]
        result = json.loads(next(line.removeprefix("TIMEZONE_RESULT=") for line in completed.stdout.splitlines()
                                 if line.startswith("TIMEZONE_RESULT=")))
        assert result["process_zone"] == zone
        row = result["planning"]
        assert "error" not in row, row
        assert row.get("stopped_at_budget"), row
        assert not row["solved"]
        budget = row["budget"]
        assert budget["instant_charge"] is instant_charge
        assert budget["hours"] == pytest.approx(expected_hours)
        expected_capacity = expected_hours * budget["power"] * budget["efficiency"]
        assert budget["max_possible"] == pytest.approx(expected_capacity)
        # This fixture requests 30% -> 100% of a 100 kWh battery.
        assert budget["energy_needed"] == pytest.approx(min(70.0, expected_capacity))
        assert budget["target_soc"] == pytest.approx(30.0 + min(70.0, expected_capacity))
        rows.append(row)
    assert rows[0]["input_digest"] == rows[1]["input_digest"]
    assert rows[0]["budget"] == rows[1]["budget"]
