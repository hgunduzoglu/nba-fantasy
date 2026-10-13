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


def test_league_config_for_14_teams(config):
    from fdo.calibration.bots import league_config

    c14 = league_config(config, 14)
    assert c14.league.teams == 14 and c14.league.rounds == 13 and c14.league.my_seat == 14
    assert sum(c14.model.bots.mix.values()) == 13 and sum(c14.roster.slots.values()) == 13
    assert league_config(config, 16) is config


def test_names_import_and_auto_exclusion_14_teams(tmp_path, nostd, config):
    import pandas as pd

    from fdo.calibration.bots import auto_mask, league_config
    from fdo.draft.io import import_names

    ds, universe = nostd
    c14 = league_config(config, 14)
    mat = simulate_matrix(universe, c14, 4, seed=3)
    logs = matrix_to_logs(mat, universe, c14)
    names = ds.names()
    rows = [{"Pick": p.overall_pick, "Player": names[p.player_id], "Auto": "x" if p.overall_pick % 10 == 0 else ""}
            for p in logs[0].picks]
    text = pd.DataFrame(rows).to_csv(index=False, sep="\t")
    log, notes = import_names(text, ds.players, c14)
    assert [p.player_id for p in log.picks] == [p.player_id for p in logs[0].picks]
    assert log.teams == 14 and len(log) == 14 * 13
    assert auto_mask([log]).sum() == 18 and "18 otomatik" in notes[0]

    fit = fit_sigma([log, *logs[1:]], ds, universe, c14, sigma0_grid=(1.0,), sigma1_grid=(0.1,), n_sims=5, seed=1)
    assert fit.auto_picks == 18
    full = deviation_moments(logs_to_matrix([log], universe)[0], universe)["n"].sum()
    kept = deviation_moments(logs_to_matrix([log], universe)[0], universe, exclude=auto_mask([log]))["n"].sum()
    assert kept < full


def test_calibrate_bots_script_with_14_team_name_logs(tmp_path, config):
    import pandas as pd

    from calibrate_bots import main

    from fdo.bots.universe import build_universe
    from fdo.calibration.bots import league_config
    from fdo.ingest import load_dataset
    from fdo.ingest.synthetic import write_synthetic

    paths = write_synthetic(tmp_path, 300, 5, config, "2026-10-01")
    ds, _ = load_dataset(paths["players"], paths["projections"], paths["adp"], config=config)
    u = build_universe(ds, config)
    c14 = league_config(config, 14)
    (tmp_path / "logs").mkdir()
    names = ds.names()
    for i, log in enumerate(matrix_to_logs(simulate_matrix(u, c14, 2, seed=8), u, c14)):
        pd.DataFrame([{"pick": p.overall_pick, "player": names[p.player_id]} for p in log.picks]).to_csv(
            tmp_path / "logs" / f"mock_{i}.csv", index=False)
    assert main(["--logs", str(tmp_path / "logs" / "*.csv"), "--data", str(tmp_path), "--teams", "14",
                 "--sigma0", "1", "--sigma1", "0.1", "--sims", "5", "--out", str(tmp_path / "rep")]) == 0
    assert "14 takım × 13 tur" in (tmp_path / "rep" / "bot_calibration.md").read_text(encoding="utf-8")
