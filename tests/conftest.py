from __future__ import annotations

import pytest

from fdo.config import load_config


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture(scope="session")
def config_3rr(config):
    return config.with_overrides({"league": {"third_round_reversal": True}})


@pytest.fixture(scope="session")
def synthetic_ds(config):
    import numpy as np

    from fdo.ingest import make_synthetic

    return make_synthetic(400, np.random.default_rng(7), config, as_of="2026-10-01", seed=7)


@pytest.fixture(scope="session")
def universe(synthetic_ds, config):
    from fdo.bots.universe import build_universe

    return build_universe(synthetic_ds, config)
