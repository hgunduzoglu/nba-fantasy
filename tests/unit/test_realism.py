import pandas as pd
import pytest

from fdo.realism.metrics import compute_metrics, reach_class, run_mock_batch
from fdo.realism.report import build_report, md_table


@pytest.fixture(scope="module")
def metrics(universe, config):
    batch = run_mock_batch(universe, config, 20, seed=3, chunk=8)
    return compute_metrics(batch, universe, config)


def test_batch_shapes(metrics):
    assert metrics.n_mocks == 20
    assert list(metrics.rounds.index) == list(range(1, 14))
    assert metrics.positions.shape == (13, 5)
    assert metrics.positions.sum(axis=1).round(6).eq(1).all()


def test_rosters_complete_with_feasibility(metrics):
    assert metrics.incomplete == 0


def test_diversity_in_range(metrics):
    d = metrics.diversity
    assert 0 < d["jaccard_mean"] <= 1
    assert d["kendall_tau_mean"] < 0.98


def test_reach_class(config):
    p = config.model.realism
    assert reach_class(3.0, p) == "bad"
    assert reach_class(2.0, p) == "warn"
    assert reach_class(0.0, p) == "neutral"
    assert reach_class(-3.0, p) == "slide"


def test_report_renders(metrics, config):
    md = build_report(metrics, config, is_synthetic=True)
    assert "SENTETİK VERİ" in md
    assert "uncalibrated" in md


def test_md_table():
    out = md_table(pd.DataFrame({"a": [1.0, float("nan")], "b": ["x", "y"]}), index=False)
    assert out.splitlines()[0] == "| a | b |"
    assert "| 1.000 | x |" in out
