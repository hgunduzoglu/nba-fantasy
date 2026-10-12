from __future__ import annotations

import pytest

from fdo.config import load_config


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture(scope="session")
def config_3rr(config):
    return config.with_overrides({"league": {"third_round_reversal": True}})
