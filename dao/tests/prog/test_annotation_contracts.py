"""Preserve runtime contracts where annotations are inspected or describe self."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from dao.prog.config.models.report import ReportConfig
from dao.prog.da_debug import RecordingIO, ReplayIO


@pytest.mark.parametrize("value", [None, "sensor.co2", ["sensor.co2"], []])
def test_co2_configuration_keeps_scalar_list_and_null_roundtrips(value):
    config = ReportConfig.model_validate({"entity co2-intensity": value})
    serialized = config.model_dump(mode="json", by_alias=True)
    assert serialized["entity co2-intensity"] == value
    assert ReportConfig.model_validate(serialized).co2_intensity_sensor == config.co2_intensity_sensor


def test_co2_configuration_still_validates_entity_ids():
    with pytest.raises(ValidationError):
        ReportConfig.model_validate({"entity co2-intensity": "invalid entity"})
    field = ReportConfig.model_json_schema()["properties"]["entity co2-intensity"]
    assert sum(option.get("type") == "null" for option in field["anyOf"]) == 1


@pytest.mark.parametrize("context_type", [RecordingIO, ReplayIO])
@pytest.mark.parametrize("fail", [False, True])
def test_inherited_debug_context_returns_self_and_preserves_exception(context_type, fail):
    class ChildContext(context_type):
        pass

    # Isolate patch installation and snapshot I/O; execute the inherited context
    # protocol itself, including cleanup and propagation of the caller's error.
    context = ChildContext.__new__(ChildContext)
    context._install_patches = Mock()
    context._patches = Mock()
    context._freeze = None
    if context_type is RecordingIO:
        context._write_snapshot = Mock()
    error = RuntimeError("synthetic context failure")

    def run_context():
        with context as entered:
            assert entered is context
            if fail:
                raise error

    if fail:
        with pytest.raises(RuntimeError) as caught:
            run_context()
        assert caught.value is error
    else:
        run_context()
    context._install_patches.assert_called_once_with()
    context._patches.restore.assert_called_once_with()
    if context_type is RecordingIO:
        context._write_snapshot.assert_called_once_with(error if fail else None)
