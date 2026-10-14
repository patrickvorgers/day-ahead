"""Keep report periods independent across instances and recalculations."""

import datetime as dt
from copy import deepcopy
from types import SimpleNamespace

import pytest

from dao.prog.config.models.report import ReportConfig
from dao.prog.da_base import DaBase
from dao.prog.da_report import Report


@pytest.fixture
def report_factory(monkeypatch):
    def initialize_base(self, file_name=None):
        self.config = SimpleNamespace(report=ReportConfig(), graphics=SimpleNamespace(style="default"))
        self.prices_options = SimpleNamespace(last_invoice=dt.date(2026, 1, 1))

    monkeypatch.setattr(DaBase, "__init__", initialize_base)
    return lambda now: Report(_now=now)


def test_constructing_another_report_preserves_existing_periods(report_factory):
    first_now = dt.datetime(2026, 1, 14, 12, tzinfo=dt.UTC)
    second_now = first_now + dt.timedelta(days=1)
    first = report_factory(first_now)
    original = deepcopy(first.periodes)
    second = report_factory(second_now)

    assert first.periodes == original
    assert first.periodes is not second.periodes
    assert first.periodes["vandaag"]["vanaf"] == first_now.replace(hour=0, tzinfo=None)
    assert second.periodes["vandaag"]["vanaf"] == second_now.replace(hour=0, tzinfo=None)


def test_recalculating_periods_and_custom_keys_stay_with_their_report(report_factory):
    now = dt.datetime(2026, 1, 14, 12, tzinfo=dt.UTC)
    first = report_factory(now)
    second = report_factory(now)
    original = deepcopy(first.periodes)

    second.periodes["custom"] = {"interval": "dag"}
    second.make_periodes(_now=now + dt.timedelta(days=1))

    assert first.periodes == original
    assert "custom" not in first.periodes
    assert second.periodes["custom"] == {"interval": "dag"}
    assert second.periodes["vandaag"]["vanaf"] == (now + dt.timedelta(days=1)).replace(hour=0, tzinfo=None)
