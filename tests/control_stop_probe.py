"""Execute repository output blocks with fixed dispatch values and local sinks.

No application constructor, optimizer, HA client or network transport is used.
The arithmetic and service-call statements are compiled from the current source,
not reproduced in the test. This isolates publication from solver decisions.
"""

import ast
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

SOURCE = Path(__file__).resolve().parents[1] / "dao/prog/day_ahead.py"


def assigns(node, name):
    return isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)


def output_blocks():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    calculator, = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DaCalc"]
    method, = [node for node in calculator.body if isinstance(node, ast.FunctionDef) and node.name == "calc_optimum"]
    ev, = [node for node in ast.walk(method) if isinstance(node, ast.For)
           and any(assigns(statement, "new_ampere_state") for statement in node.body)]
    first = next(index for index, node in enumerate(ev.body) if assigns(node, "new_ampere_state"))
    last, = [index for index, node in enumerate(ev.body) if isinstance(node, ast.If)
             and "ev_position[e]" in ast.unparse(node.test) and "ev_plugged_in[e]" in ast.unparse(node.test)]
    battery, = [node for node in ast.walk(method) if isinstance(node, ast.For)
                and any(assigns(statement, "netto_vermogen_bat") for statement in node.body)]
    stop, = [index for index, node in enumerate(battery.body) if isinstance(node, ast.If)
             and ast.unparse(node.test) == "stop_omvormer is None"]
    publish, = [node for node in battery.body if isinstance(node, ast.If)
                and ast.unparse(node.test) == "self.debug"
                and any(isinstance(item, ast.keyword) and item.arg == "entity_id"
                        and isinstance(item.value, ast.Name) and item.value.id == "stop_inverter_id"
                        for item in ast.walk(node))]
    return ev.body[first:last + 1], battery.body[:stop + 1] + [publish]


class LocalDevices:
    """Deliberately has no client/session/base class that could contact HA."""

    def __init__(self, debug=False):
        self.debug = debug
        self.calls = []
        self.ev_options = [SimpleNamespace(name="Synthetic EV")]
        self.battery_options = [SimpleNamespace(
            name="Synthetic inverter", minimum_power=1000,
            entity_set_operating_mode_on="on", entity_set_operating_mode_off="off",
            entity_stop_inverter="input_datetime.synthetic_inverter_stop",
        )]

    def get_state(self, entity):
        return SimpleNamespace(state={"switch.synthetic_charge": "off", "input_number.synthetic_ampere": "16"}[entity])

    def call_service(self, service, **kwargs):
        self.calls.append({"method": "call_service", "service": service, **kwargs})

    def set_value(self, entity, value):
        self.calls.append({"method": "set_value", "entity": entity, "value": value})

    def turn_on(self, entity):
        self.calls.append({"method": "turn_on", "entity": entity})

    def turn_off(self, entity):
        self.calls.append({"method": "turn_off", "entity": entity})

    def set_entity_value(self, key, options, value):
        self.calls.append({"method": "set_entity_value", "key": key, "value": value})

    def set_entity_option(self, key, options, value):
        self.calls.append({"method": "set_entity_option", "key": key, "value": value})


def probe(request):
    instant = dt.datetime.fromisoformat(request["instant"])
    local = instant.astimezone(ZoneInfo(request["ha_zone"])).replace(tzinfo=None)
    seconds = 900
    remaining = seconds - int(instant.timestamp()) % seconds
    fraction = 0.5
    def variable(value):
        return SimpleNamespace(x=value)
    rows = {}
    for kind, nodes in zip(("ev", "inverter"), output_blocks(), strict=True):
        devices = LocalDevices(debug=request.get("debug", False))
        context = {
            "dt": dt, "_LOGGER": logging.getLogger(__name__), "self": devices,
            "start_dt": local, "hour_fraction": [remaining / 3600], "e": 0, "b": 0,
            "old_switch_state": "off", "old_ampere_state": "16",
            "entity_charge_switch": "switch.synthetic_charge",
            "entity_charging_ampere": "input_number.synthetic_ampere",
            "entity_stop_laden": "input_datetime.synthetic_ev_stop",
            "ECS": [2], "stage_factor": [[[variable(0)], [variable(fraction)]]],
            "ev_charge_stages": [[{"ampere": 0}, {"ampere": 16}]],
            "energy_needed": [1.0], "ev_accu_in": [[variable(0.01)]],
            "ev_position": ["home"], "ev_plugged_in": [True],
            "ac_to_dc": [[variable(0.5)]], "ac_from_dc": [[variable(0)]],
            "grid_balance": False, "reduce_power_low_soc": [[]],
            "reduce_power_high_soc": [[]], "start_soc": [50],
            "from_battery": 0, "from_pv": 0, "from_ac": 0, "calculated_soc": 50,
        }
        devices.interval_s = seconds
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), context)
        expected_epoch = int(instant.timestamp() + fraction * (remaining if kind == "ev" else seconds))
        rows[kind] = {
            "calls": devices.calls, "calculated_epoch": int(context["new_ts"]),
            "expected_epoch": expected_epoch,
            "expected_label": dt.datetime.fromtimestamp(expected_epoch, ZoneInfo(request["ha_zone"])).strftime("%Y-%m-%d %H:%M"),
        }
    return {"process_zone": os.environ["TZ"], "input": request, **rows}


if __name__ == "__main__":
    print(json.dumps(probe(json.loads(sys.argv[1])), sort_keys=True))
