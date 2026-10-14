"""Compare actual output statements with fixed post-solver dispatch values."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HA_ZONE = "Europe/Amsterdam"
CASES = [
    ("winter", "2026-01-14T08:07:00+00:00"),
    ("summer", "2026-07-01T07:07:00+00:00"),
    ("spring-jump", "2026-03-29T00:57:00+00:00"),
    ("autumn-jump", "2026-10-25T00:57:00+00:00"),
    ("first-0207", "2026-10-25T00:07:00+00:00"),
    ("second-0207", "2026-10-25T01:07:00+00:00"),
]
pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="Subprocess timezone comparison requires POSIX tzset")


def run_probe(payload, zone):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests/control_stop_probe.py"), json.dumps(payload)],
        cwd=ROOT, env={**os.environ, "TZ": zone}, capture_output=True, text=True, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout + completed.stderr)
    row = json.loads(completed.stdout)
    if row["process_zone"] != zone or row["input"] != payload:
        raise RuntimeError("Probe process zone or dispatch input changed")
    return row


@pytest.fixture(scope="module", params=CASES, ids=[case[0] for case in CASES])
def outputs(request):
    name, instant = request.param
    payload = {"instant": instant, "ha_zone": HA_ZONE}
    return name, {zone: run_probe(payload, zone) for zone in ("UTC", HA_ZONE)}


@pytest.fixture(autouse=True)
def expected_control_failure(request):
    if request.node.originalname == "test_inverter_stop_payload_uses_ha_clock":
        case = request.node.callspec.params["outputs"][0]
        if case in ("spring-jump", "autumn-jump"):
            request.node.add_marker(pytest.mark.xfail(
                strict=True, raises=AssertionError,
                reason="Measured pre-fix output mismatch; see docs/ruff-control-stop-baseline.md",
            ))


def assert_stop(row, kind, entity):
    calls = [call for call in row[kind]["calls"] if call["method"] == "call_service"]
    assert calls == [{"method": "call_service", "service": "set_datetime", "entity_id": entity,
                      "datetime": row[kind]["expected_label"]}], row[kind]


def test_ev_stop_payload_uses_ha_clock(outputs):
    _, rows = outputs
    for row in rows.values():
        assert_stop(row, "ev", "input_datetime.synthetic_ev_stop")
    assert rows["UTC"]["ev"]["calls"] == rows[HA_ZONE]["ev"]["calls"]


def test_inverter_stop_payload_uses_ha_clock(outputs):
    _, rows = outputs
    for row in rows.values():
        assert_stop(row, "inverter", "input_datetime.synthetic_inverter_stop")
    assert rows["UTC"]["inverter"]["calls"] == rows[HA_ZONE]["inverter"]["calls"]


@pytest.mark.parametrize("zone", ["UTC", HA_ZONE])
def test_debug_output_blocks_emit_no_commands(zone):
    row = run_probe({"instant": "2026-03-29T00:57:00+00:00", "ha_zone": HA_ZONE, "debug": True}, zone)
    assert row["ev"]["calls"] == []
    assert row["inverter"]["calls"] == []
