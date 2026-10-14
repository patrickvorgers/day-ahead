"""Run real application time boundaries in one disposable, timezone-specific process."""

import datetime as dt
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from dao.lib import da_prices
from dao.prog import da_scheduler
from dao.prog.config.models.report import ReportConfig
from dao.prog.da_base import DaBase
from dao.prog.da_report import Report


def local_clock(epoch):
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(epoch, tz)

        @classmethod
        def today(cls):
            return cls.now()

    class Date(dt.date):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(epoch)

    return SimpleNamespace(datetime=Clock, timedelta=dt.timedelta, date=Date, time=dt.time)


def probe(request):
    instant = dt.datetime.fromisoformat(request["instant"])
    ha_zone = ZoneInfo(request["ha_zone"])
    epoch = instant.timestamp()

    clock_module = local_clock(epoch)

    def initialize_report(self, file_name=None):
        self.config = SimpleNamespace(report=ReportConfig(), graphics=SimpleNamespace(style="default"),
                                      time_zone=request["ha_zone"])
        self.time_zone = request["ha_zone"]
        self.prices_options = SimpleNamespace(last_invoice=dt.date(2026, 1, 1))

    with patch.object(DaBase, "__init__", initialize_report), patch("dao.prog.da_report.datetime", clock_module):
        report = Report()

    def timestamp(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=ha_zone)
        return int(value.timestamp())

    periods = {name: [timestamp(value["vanaf"]), timestamp(value["tot"])]
               for name, value in report.periodes.items()}

    db = Mock()
    db.get_time_border_record.return_value = None
    key = Mock()
    key.resolve.return_value = "synthetic-key"
    configuration = SimpleNamespace(interval="1hour", time_zone=request["ha_zone"],
                                    prices=SimpleNamespace(entsoe_api_key=key))
    prices = da_prices.DaPrices(configuration, db, country="NL", time_zone=request["ha_zone"])
    provider = Mock()
    provider.query_day_ahead_prices.return_value = pd.DataFrame()
    with patch.object(da_prices, "datetime", clock_module), patch.object(
        da_prices, "EntsoePandasClient", return_value=provider,
    ):
        prices.get_prices("entsoe")
    query = provider.query_day_ahead_prices.call_args.kwargs

    class EndIteration(Exception):
        pass

    next_instant = instant.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    expected_pattern = next_instant.astimezone(ha_zone).strftime("%H%M")
    clock = Mock()
    clock.now.side_effect = [clock_module.datetime.now(dt.UTC), clock_module.datetime.now(dt.UTC), EndIteration()]
    scheduler = da_scheduler.DaScheduler.__new__(da_scheduler.DaScheduler)
    scheduler.active = True
    scheduler.offset_start = 0
    scheduler.time_zone = request["ha_zone"]
    scheduler.scheduler_tasks = {expected_pattern: "calculate"}
    scheduler.tasks = {"calculate": {"function": "calculate"}}
    scheduler.run_task_process = Mock(return_value=True)
    with patch.object(da_scheduler, "datetime", SimpleNamespace(datetime=clock, timedelta=dt.timedelta, UTC=dt.UTC)), \
            patch.object(da_scheduler, "time", SimpleNamespace(sleep=Mock())):
        try:
            scheduler.scheduler()
        except EndIteration:
            pass

    return {
        "process_zone": os.environ["TZ"], "ha_zone": request["ha_zone"],
        "instant": instant.isoformat(), "periods": periods,
        "price_bounds": [int(query["start"].timestamp()), int(query["end"].timestamp())],
        "dispatched": [call.args[0] for call in scheduler.run_task_process.call_args_list],
    }


def planning_probe(request):
    process_zone = os.environ["TZ"]
    # Importing the scenario helpers pins UTC. Build a single canonical fixture
    # in HA time, then restore the requested process TZ before application code.
    from mip import Model

    from dao.prog import da_debug
    from dao.prog.scenarios.build_snapshot import (
        build_config,
        build_snapshot,
        resolve_ev,
    )
    from dao.prog.scenarios.loader import parse_scenario
    from dao.prog.scenarios.runner import _solar_patch

    instant = dt.datetime.fromisoformat(request["instant"])
    local = instant.astimezone(ZoneInfo(request["ha_zone"]))
    scenario = parse_scenario({
        "id": "timezone-contract", "description": "Synthetic deterministic charging window",
        "start": local.strftime("%Y-%m-%d %H:%M"),
        "prices": {"cons": [0.2 + hour / 100 for hour in range(24)], "prod": [0.01] * 24},
        "ev": {"target": "golf", "plugged_in": True, "position": "home",
               "actual_soc": 30.0, "wished_level": request.get("wished_level", 35.0),
               "instant_charge": request.get("instant_charge", False),
               "ready": "+3h"},
        "expect": {"solved": True},
    })
    os.environ["TZ"] = request["ha_zone"]
    time.tzset()
    configuration = build_config(scenario)
    configuration["max_gap"] = {"value": 0.00001}
    expanded = resolve_ev(scenario, configuration)
    target = configuration["electric_vehicle"][expanded.target_index]
    if request.get("budget_only"):
        target["capacity"] = 100.0
        if request.get("instant_charge"):
            target["entity_instant_start"] = "input_boolean.synthetic_instant_charge"
            target["entity_instant_level"] = "input_number.synthetic_instant_level"
            expanded.states[target["entity_instant_start"]] = "on"
            expanded.states[target["entity_instant_level"]] = request["wished_level"]
    deadline_entity = target["charge_scheduler"]["entity_ready_datetime"]
    expanded.states[deadline_entity] = request["ready"]
    snapshot = build_snapshot(scenario, config=configuration, ev_states=expanded.states)
    # The physical quarter-hour grid is identical in both subprocesses. Local
    # labels may skip an hour or repeat it; epoch values never skip or repeat.
    instants = [instant + dt.timedelta(minutes=15 * index) for index in range(96)]
    labels = [value.astimezone(ZoneInfo(request["ha_zone"])).replace(tzinfo=None) for value in instants]
    price_frame = pd.DataFrame({"time": labels, "da_ex": [0.2 + index / 1000 for index in range(96)],
                               "da_cons": [0.2 + index / 1000 for index in range(96)],
                               "da_prod": [0.01] * 96, "datasoort": ["expected"] * 96})
    price_frame.index = pd.to_datetime(price_frame["time"])
    prog_frame = pd.DataFrame({"time": [int(value.timestamp()) for value in instants], "tijd": labels,
                              "temp": [6.0] * 96, "glob_rad": [0.0] * 96})
    prog_frame.index = pd.to_datetime(prog_frame["tijd"])
    snapshot["price_data"] = da_debug._dataframe_to_payload(price_frame)
    snapshot["prog_data"] = da_debug._dataframe_to_payload(prog_frame)
    snapshot["ha_context"]["time_zone"] = request["ha_zone"]
    snapshot["config"]["time_zone"] = request["ha_zone"]
    # Avoid freezegun's naive-UTC clock: this probe supplies the same physical
    # instant through a process-local now(), including the correct fold bit.
    snapshot["meta"]["captured_at"] = None
    os.environ["TZ"] = process_zone
    time.tzset()
    da_debug._ensure_day_ahead_importable()
    from dao.prog import day_ahead

    observed = {"input_digest": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()}
    messages = io.StringIO()
    handler = logging.StreamHandler(messages)
    handler.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(handler)

    class StopAtEVBudget(Exception):
        """Stop an isolated capacity test before model constraints or solving."""

    def trace(frame, event, arg):
        if frame.f_code.co_name == "calc_optimum":
            values = frame.f_locals
            if "start_interval_dt" in values and "start_calendar" not in observed:
                observed["start_calendar"] = {
                    "start_epoch": values["start_ts"],
                    "start_label": values["start_dt"].isoformat(),
                    "interval_epoch": values["start_interval_ts"],
                    "interval_label": values["start_interval_dt"].isoformat(),
                }
            if "end_fixed_ts" in values and "end_fixed_dt" in values and "forecast_end" not in observed:
                observed["forecast_end"] = {
                    "label": values["end_fixed_dt"].isoformat(),
                    "query_epoch": values["end_fixed_ts"],
                    "input_end_epoch": int(instants[-1].timestamp()) + 900,
                }
            if "num_quaters" in values and "price_coverage" not in observed:
                observed["price_coverage"] = {
                    "start_label": values["start"].isoformat(),
                    "last_label": values["end_prog"].isoformat(),
                    "expected_quarters": values["num_quaters"],
                    "available_quarters": len(values["price_data"]),
                }
            if "first_interval_nr" in values and "baseload_selection" not in observed:
                observed["baseload_selection"] = {
                    "first_label": values["time_first_interval"].isoformat(),
                    "first_interval_nr": values["first_interval_nr"],
                    "price_count": len(values["price_data"]),
                    "forecast_count": len(values["prog_data"]),
                }
            if "hours_avail" in values and "ev_stages" in values and "available_hours" not in observed:
                observed["available_hours"] = values["hours_avail"]
                observed["charging_clock"] = {
                    "start_label": values["start_dt"].isoformat(),
                    "ready_label": values["ready"].isoformat(),
                }
            if request.get("budget_only") and values.get("energy_needed"):
                index = values["e"]
                observed["budget"] = {
                    "instant_charge": values["instant_charge"],
                    "hours": values["hours_avail"],
                    "power": values["max_power"][index],
                    "efficiency": values["ev_charge_stages"][index][-1]["efficiency"],
                    "max_possible": values["max_possible"],
                    "energy_needed": values["energy_needed"][index],
                    "target_soc": values["wished_level"][index],
                }
                raise StopAtEVBudget
            if event == "return":
                observed["start_epoch"] = values.get("start_ts")
                observed["returned_false"] = arg is False
                if "start_calendar" in observed:
                    observed["exit_line"] = frame.f_lineno
                # Use the calculator's actual epoch grid, not a second
                # process-dependent conversion of its local display labels.
                times = values.get("ts", [])
                energy = values.get("ev_accu_in", [])
                if energy:
                    observed["plan"] = [[int(moment), round(float(variable.x), 6)]
                                        for moment, variable in zip(times, energy[0], strict=False)
                                        if variable.x is not None and variable.x > 1e-6]
        return trace

    with tempfile.TemporaryDirectory(prefix="dao-timezone-") as directory:
        options = Path(directory) / "options.json"
        options.write_text("{}", encoding="utf-8")
        try:
            with da_debug.ReplayIO(snapshot, solver_threads=1) as replay:
                replay._patches.set(DaBase, "calc_solar_predictions", _solar_patch(scenario))
                clock_module = local_clock(instant.timestamp())
                captured_optimize = Model.optimize

                def optimize(model, *args, **kwargs):
                    model.seed = 17
                    return captured_optimize(model, *args, **kwargs)

                with patch.object(day_ahead, "dt", clock_module), patch.object(Model, "optimize", optimize):
                    calculator = day_ahead.DaCalc(str(options))
                    calculator._debug_capture_vars = True
                    sys.settrace(trace)
                    try:
                        try:
                            calculator.calc_optimum()
                        except StopAtEVBudget:
                            observed["stopped_at_budget"] = True
                        except Exception as error:
                            observed["error"] = {"type": type(error).__name__, "message": str(error)}
                    finally:
                        sys.settrace(None)
                    model = replay._model
                    observed["solved"] = bool(model is not None and model.num_solutions > 0)
                    observed["objective"] = model.objective_value if observed["solved"] else None
        finally:
            sys.settrace(None)
            root.removeHandler(handler)
            handler.close()
    observed["warnings"] = messages.getvalue().strip()
    return observed


if __name__ == "__main__":
    data = json.loads(sys.argv[1])
    result = probe(data)
    result["planning"] = planning_probe(data)
    print("TIMEZONE_RESULT=" + json.dumps(result, sort_keys=True))
