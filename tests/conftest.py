import sys
from pathlib import Path

import pytest

# The contracts package is a workspace package; importable without installing.
CONTRACTS = Path(__file__).resolve().parents[1] / "packages" / "contracts" / "src"
if str(CONTRACTS) not in sys.path:
    sys.path.insert(0, str(CONTRACTS))

API = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

# `engines/` is a top-level package at the repo root, and since `P2.1` the
# converter lives under it too, so this is the only path the engine needs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def sample_twb_bytes() -> bytes:
    return (FIXTURES / "sample.twb").read_bytes()


@pytest.fixture
def sample_twb_path() -> Path:
    return FIXTURES / "sample.twb"


@pytest.fixture
def clashing_twb_bytes() -> bytes:
    return (FIXTURES / "clashes.twb").read_bytes()


@pytest.fixture
def clashing_twb_path() -> Path:
    return FIXTURES / "clashes.twb"


@pytest.fixture
def federated_twb_bytes() -> bytes:
    return (FIXTURES / "federated.twb").read_bytes()


@pytest.fixture
def federated_twb_path() -> Path:
    return FIXTURES / "federated.twb"


def pytest_addoption(parser):
    """`--update-golden` rewrites the checked-in `.twb` output fixtures.

    Deliberately not the default and deliberately not automatic: a golden that
    regenerates itself agrees with every change, including the wrong ones. The
    flag exists so that updating one is a decision someone made and a diff
    someone read.
    """
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="rewrite the golden .twb fixtures from the current writer output",
    )
