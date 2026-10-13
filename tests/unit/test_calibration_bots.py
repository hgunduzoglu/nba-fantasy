import pytest

from fdo.calibration.bots import (
    deviation_moments,
    fit_sigma,
    logs_to_matrix,
    matrix_to_logs,
    simulate_matrix,
    survival_reliability,
    user_checkpoints,
    with_sigma,
)


@pytest.fixture(scope="module")
def nostd(synthetic_ds, config):
    """Yahoo verisi gibi ``adp_std``'siz: σ = σ₀ + σ₁·A."""
    import dataclasses

    import numpy as np

    from fdo.bots.universe import build_universe

    ds = dataclasses.replace(synthetic_ds, adp=synthetic_ds.adp.assign(adp_std=np.nan))
    return ds, build_universe(ds, config)


@pytest.fixture(scope="module")
def truth(nostd, config):
    ds, universe = nostd
    cfg = config.with_overrides({"model": {"bots": {"sigma0": 3.0, "sigma1": 0.1}}})
    mat = simulate_matrix(with_sigma(universe, ds, cfg), cfg, 40, seed=99)
    return cfg, mat, matrix_to_logs(mat, universe, config)


def test_logs_roundtrip(truth, nostd):
    universe = nostd[1]
    _, mat, logs = truth
    back, missing = logs_to_matrix(logs, universe)
    assert missing == 0 and (back == mat).all()
    mom = deviation_moments(mat, universe)
    assert mom["n"].sum() > 0 and list(mom.columns) == ["n", "p10", "p50", "p90"]


def test_fit_recovers_sigma(truth, nostd, config):
    ds, universe = nostd
    _, _, logs = truth
    fit = fit_sigma(logs, ds, universe, config, sigma0_grid=(1.0, 3.0, 6.0),
                    sigma1_grid=(0.03, 0.1, 0.2), n_sims=40, seed=5)
    assert fit.best == {"sigma0": 3.0, "sigma1": 0.1}
    assert fit.n_logs == 40 and len(fit.grid) == 9 and fit.param_share == 1.0


def test_survival_reliability_is_calibrated_under_truth(truth, nostd, config):
    ds, universe = nostd
    cfg, mat, _ = truth
    sim = simulate_matrix(with_sigma(universe, ds, cfg), cfg, 200, seed=7)
    table, brier = survival_reliability(sim, mat, user_checkpoints(config), universe.n, n_bins=5)
    assert 0 < brier < 0.25
    big = table[table["n"] >= 50]
    assert len(big) >= 3 and (abs(big["predicted"] - big["observed"]) < 0.12).all()


def test_calibrate_bots_script(tmp_path, config):
    from calibrate_bots import main

    from fdo.bots.universe import build_universe
    from fdo.draft import io as draft_io
    from fdo.ingest import load_dataset
    from fdo.ingest.synthetic import write_synthetic

    paths = write_synthetic(tmp_path, 300, 4, config, "2026-10-01")
    ds, _ = load_dataset(paths["players"], paths["projections"], paths["adp"], config=config)
    u = build_universe(ds, config)
    mat = simulate_matrix(u, config, 3, seed=2)
    (tmp_path / "logs").mkdir()
    for i, log in enumerate(matrix_to_logs(mat, u, config)):
        draft_io.save(log, tmp_path / "logs" / f"draft_{i}.csv")
    assert main(["--logs", str(tmp_path / "logs" / "*.csv"), "--data", str(tmp_path), "--sigma0", "1,2",
                 "--sigma1", "0.1", "--sims", "10", "--out", str(tmp_path / "rep")]) == 0
    text = (tmp_path / "rep" / "bot_calibration.md").read_text(encoding="utf-8")
    assert "En iyi" in text and "Brier" in text
