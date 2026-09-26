"""Per-user product access: an administrator decides who may use which product.

Tableau, MicroStrategy and Qlik migration are separate products. A direction is
usable by a person when its engine is installed, the licence includes it, and -
unless they are an administrator - an administrator has given them access.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.dashboardbridge.conftest import FIXTURE_EMAIL, FIXTURE_PASSWORD

PREFIX = "/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "a long enough password"


def _add(client, email: str, **extra):
    response = client.post(f"{PREFIX}/users", json={"email": email, "display_name": email.split("@")[0],
                                                    "password": PASSWORD, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _sign_in(client, email: str, password: str = PASSWORD) -> None:
    assert client.post(f"{PREFIX}/auth/login", json={"email": email, "password": password}).status_code == 200


def _states(client) -> dict[str, str]:
    return {d["source_platform"]: d["state"]
            for d in client.get(f"{PREFIX}/directions").json()["directions"] if d["target_platform"] == "powerbi"}


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def test_a_new_person_gets_every_licensed_product_unless_told_otherwise(api):
    user = _add(api.client, "ann@example.test")
    assert user["products"] == ["microstrategy", "qlik", "tableau"]


def test_an_administrator_chooses_products_when_adding_and_later(api):
    user = _add(api.client, "bob@example.test", products=["tableau"])
    assert user["products"] == ["tableau"]
    updated = api.client.patch(f"{PREFIX}/users/{user['user_id']}", json={"products": ["tableau", "qlik"]})
    assert updated.status_code == 200 and updated.json()["products"] == ["qlik", "tableau"]
    listed = {u["email"]: u["products"] for u in api.client.get(f"{PREFIX}/users").json()["users"]}
    assert listed["bob@example.test"] == ["qlik", "tableau"]


def test_an_unknown_product_is_refused_not_dropped(api):
    response = api.client.post(f"{PREFIX}/users", json={"email": "c@example.test", "password": PASSWORD,
                                                        "products": ["tableau", "cognos"]})
    assert response.status_code == 422
    assert "cognos" in response.json()["message"]


def test_a_person_sees_and_uses_only_what_they_were_given(api):
    _add(api.client, "dee@example.test", products=["tableau"])
    _sign_in(api.client, "dee@example.test")
    states = _states(api.client)
    assert states["tableau"] == "available"
    for source, module in (("qlik", "qlik2pbi"), ("microstrategy", "mstr2pbi")):
        assert states[source] == ("not_granted" if _installed(module) else "not_installed")
    if _installed("qlik2pbi"):
        refused = api.client.post(f"{PREFIX}/projects",
                                  json={"source_platform": "qlik", "target_platform": "powerbi", "name": "Q"})
        assert refused.status_code == 403
        assert "Ask an administrator" in refused.json()["message"]
    ok = api.client.post(f"{PREFIX}/projects",
                         json={"source_platform": "tableau", "target_platform": "powerbi", "name": "T"})
    assert ok.status_code == 201


def test_an_administrator_sees_every_installed_licensed_product_whatever_their_grants(api):
    admin = next(u for u in api.client.get(f"{PREFIX}/users").json()["users"] if u["email"] == FIXTURE_EMAIL)
    api.client.patch(f"{PREFIX}/users/{admin['user_id']}", json={"products": []})
    states = _states(api.client)
    assert states["tableau"] == "available"
    for source, module in (("qlik", "qlik2pbi"), ("microstrategy", "mstr2pbi")):
        assert states[source] == ("available" if _installed(module) else "not_installed")


def test_access_withdrawn_mid_project_stops_the_conversion(api):
    user = _add(api.client, "eve@example.test", products=["tableau"])
    _sign_in(api.client, "eve@example.test")
    project = api.client.post(f"{PREFIX}/projects",
                              json={"source_platform": "tableau", "target_platform": "powerbi", "name": "T"}).json()
    _sign_in(api.client, FIXTURE_EMAIL, FIXTURE_PASSWORD)
    api.client.patch(f"{PREFIX}/users/{user['user_id']}", json={"products": ["qlik"]})
    _sign_in(api.client, "eve@example.test")
    response = api.client.post(f"{PREFIX}/projects/{project['project_id']}/conversion", json={"ai_enabled": False})
    assert response.status_code == 403


def test_only_an_administrator_can_change_access(api):
    user = _add(api.client, "fay@example.test", products=["tableau"])
    _sign_in(api.client, "fay@example.test")
    response = api.client.patch(f"{PREFIX}/users/{user['user_id']}", json={"products": ["tableau", "qlik"]})
    assert response.status_code == 403


def test_upgrading_grants_every_existing_person_every_product(tmp_path, monkeypatch):
    """Before products were separate everyone could use everything; an upgrade must not take that away."""
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    url = f"sqlite+pysqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    cfg = Config(str(REPO_ROOT / "apps" / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO users (user_id, email, display_name, password_hash, is_admin, is_active, created_at) "
            "VALUES ('0f0f0f0f0f0f4f0f8f0f0f0f0f0f0f0f', 'old@example.test', 'old', 'x', 0, 1, '2026-01-01')"))
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        products = sorted(r[0] for r in conn.execute(sa.text("SELECT product FROM user_products")))
    engine.dispose()
    assert products == ["microstrategy", "qlik", "tableau"]


@pytest.mark.parametrize("state", ["not_granted"])
def test_the_new_state_is_in_the_contract(state):
    from dashboardbridge_contracts.enums import DirectionState

    assert DirectionState(state)
