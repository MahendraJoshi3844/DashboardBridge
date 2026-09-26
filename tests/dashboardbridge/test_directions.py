"""Engines are separate products: a deployment runs the combination it has.

A customer may buy Tableau only, MicroStrategy and Qlik, or all three. Each
direction is available only when its engine is installed *and* licensed, the API
refuses the others with the right remedy, and `GET /directions` tells the web app
which cards to open.
"""

from __future__ import annotations

import importlib.util

import pytest
from dashboardbridge_contracts.enums import DirectionState, Platform

from app.core import licensing
from engines.conversion import directions as registry

PREFIX = "/api/v1"


def _state(features, source, target=Platform.POWERBI):
    return registry.status(registry.find(source, target), features).state


# --- the registry -------------------------------------------------------------------


def test_every_direction_the_ui_offers_is_registered():
    pairs = {(d.source, d.target) for d in registry.DIRECTIONS}
    assert pairs == {
        (Platform.TABLEAU, Platform.POWERBI),
        (Platform.POWERBI, Platform.TABLEAU),
        (Platform.MICROSTRATEGY, Platform.POWERBI),
        (Platform.QLIK, Platform.POWERBI),
    }


def test_a_licence_naming_no_engine_covers_every_installed_one():
    # Licences issued before engines were sold separately carry only 'convert'.
    for source in (Platform.TABLEAU, Platform.MICROSTRATEGY, Platform.QLIK):
        direction = registry.find(source, Platform.POWERBI)
        expected = DirectionState.AVAILABLE if registry.installed(direction) else DirectionState.NOT_INSTALLED
        assert _state(["convert"], source) is expected


def test_a_licence_naming_engines_enables_exactly_those():
    pytest.importorskip("qlik2pbi")
    pytest.importorskip("mstr2pbi")
    features = ["convert", "tableau", "qlik"]
    assert _state(features, Platform.TABLEAU) is DirectionState.AVAILABLE
    assert _state(features, Platform.POWERBI, Platform.TABLEAU) is DirectionState.AVAILABLE
    assert _state(features, Platform.QLIK) is DirectionState.AVAILABLE
    status = registry.status(registry.find(Platform.MICROSTRATEGY, Platform.POWERBI), features)
    assert status.state is DirectionState.NOT_LICENSED
    assert "'microstrategy'" in status.reason


def test_an_engine_that_is_not_installed_says_so(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "mstr2pbi" else real(name, *a))
    status = registry.status(registry.find(Platform.MICROSTRATEGY, Platform.POWERBI), ["convert"])
    assert status.state is DirectionState.NOT_INSTALLED
    assert ".[microstrategy]" in status.reason and status.engine_version == ""


# --- through the gateway --------------------------------------------------------------


def _licence_with(monkeypatch, features):
    """The session licence, with its feature list replaced."""
    current = licensing.status()
    licence = current.license.__class__(**{**current.license.__dict__, "features": tuple(features)})
    patched = current.__class__(**{**current.__dict__, "license": licence})
    monkeypatch.setattr("app.api.directions.license_status", lambda: patched)
    monkeypatch.setattr("app.core.directions.license_status", lambda: patched)


def test_the_directions_endpoint_lists_every_direction(api):
    response = api.client.get(f"{PREFIX}/directions")
    assert response.status_code == 200
    states = {(d["source_platform"], d["target_platform"]): d["state"] for d in response.json()["directions"]}
    assert states[("tableau", "powerbi")] == "available"
    for source, module in (("microstrategy", "mstr2pbi"), ("qlik", "qlik2pbi")):
        installed = importlib.util.find_spec(module) is not None
        assert states[(source, "powerbi")] == ("available" if installed else "not_installed")


def test_the_directions_endpoint_needs_a_session(empty_api):
    assert empty_api.client.get(f"{PREFIX}/directions").status_code == 401


def test_an_unlicensed_direction_cannot_start_a_project(api, monkeypatch):
    pytest.importorskip("qlik2pbi")
    _licence_with(monkeypatch, ["convert", "tableau"])
    response = api.client.post(f"{PREFIX}/projects",
                               json={"source_platform": "qlik", "target_platform": "powerbi", "name": "Q"})
    assert response.status_code == 402
    assert "not included in this licence" in response.json()["message"]
    ok = api.client.post(f"{PREFIX}/projects",
                         json={"source_platform": "tableau", "target_platform": "powerbi", "name": "T"})
    assert ok.status_code == 201


def test_an_uninstalled_engine_cannot_start_a_project(api, monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "qlik2pbi" else real(name, *a))
    response = api.client.post(f"{PREFIX}/projects",
                               json={"source_platform": "qlik", "target_platform": "powerbi", "name": "Q"})
    assert response.status_code == 400
    assert "not installed" in response.json()["message"]
    listed = {d["source_platform"]: d["state"] for d in api.client.get(f"{PREFIX}/directions").json()["directions"]}
    assert listed["qlik"] == "not_installed"


def test_a_direction_withdrawn_after_the_project_began_stops_the_conversion(api, monkeypatch):
    project = api.client.post(f"{PREFIX}/projects",
                              json={"source_platform": "tableau", "target_platform": "powerbi", "name": "T"}).json()
    _licence_with(monkeypatch, ["convert", "qlik"])
    response = api.client.post(f"{PREFIX}/projects/{project['project_id']}/conversion", json={"ai_enabled": False})
    assert response.status_code == 402


@pytest.mark.parametrize("pair", [("qlik", "tableau"), ("microstrategy", "tableau")])
def test_a_direction_nobody_built_is_refused_at_creation(api, pair):
    response = api.client.post(f"{PREFIX}/projects",
                               json={"source_platform": pair[0], "target_platform": pair[1], "name": "X"})
    assert response.status_code == 400
    assert "not supported" in response.json()["message"]
