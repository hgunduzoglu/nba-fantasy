import numpy as np
import pandas as pd
import pytest
import yaml

from factories import varied_projections
from fdo.calibration.variance import calibrate, synthetic_gamelogs
from fdo.config import ConfigError
from fdo.matchup.ecw import category_corr_matrix, p_at_least


@pytest.fixture(scope="module")
def logs():
    proj = varied_projections(40, seed=3)
    return proj, synthetic_gamelogs(proj, 80, np.random.default_rng(5), dispersion={"reb": 2.0, "stl": 1.0})


def test_phi_recovers_dispersion(logs, config):
    proj, gl = logs
    res = calibrate(gl, config, min_games=20)
    assert res.phi["reb"] == pytest.approx(2.0, abs=0.25)
    assert res.phi["stl"] == pytest.approx(1.0, abs=0.15)
    assert res.n_players == 40 and res.n_games == 40 * 80


def test_player_variance_rescaled_to_projection(logs, config):
    proj, gl = logs
    doubled = proj.assign(reb=proj["reb"] * 2)
    a = calibrate(gl, config).variance.set_index(["player_id", "stat"])["per_game_var"]
    b = calibrate(gl, config, projections=doubled).variance.set_index(["player_id", "stat"])["per_game_var"]
    pid = proj.loc[0, "player_id"]
    mu_log = gl[gl["player_id"] == pid]["reb"].mean()
    assert b[(pid, "reb")] == pytest.approx(a[(pid, "reb")] / mu_log * proj.loc[0, "reb"] * 2, rel=1e-6)
    assert b[(pid, "stl")] == pytest.approx(a[(pid, "stl")] / gl[gl["player_id"] == pid]["stl"].mean()
                                            * proj.loc[0, "stl"], rel=1e-6)


def test_category_correlation_structure(logs, config):
    corr = calibrate(logs[1], config).category_corr
    assert list(corr.index) == list(config.categories)
    assert np.allclose(np.diag(corr), 1.0)
    assert corr.loc["FG3M", "PTS"] > 0.2                  # PTS = 2·FGM + FG3M + FTM


def test_copula_matches_independence_and_shifts_with_correlation(config):
    p = np.array([[0.5] * 9, [0.7, 0.6, 0.5, 0.4, 0.3, 0.55, 0.65, 0.45, 0.5]])
    ind = p_at_least(p, 5)
    cop = p_at_least(p, 5, np.eye(9), n_draws=20000, seed=1)
    assert np.allclose(ind, cop, atol=0.015)
    strong = np.full((9, 9), 0.6) + 0.4 * np.eye(9)
    hi = p_at_least(p[:1], 5, strong, n_draws=20000, seed=1)
    assert hi[0] < ind[0]                                  # p=0.5 ve pozitif korelasyon → kuyruklar kalınlaşır


def test_category_corr_config(config):
    config = config.with_overrides({"model": {"variance": {"category_corr": None}}})
    cfg = config.with_overrides({"model": {"variance": {"category_corr": {"PTS": {"FG3M": 0.5}}}}})
    m = category_corr_matrix(cfg)
    i, j = config.categories.index("PTS"), config.categories.index("FG3M")
    assert m[i, j] == pytest.approx(0.5) and m[j, i] == pytest.approx(0.5)
    assert category_corr_matrix(config) is None
    with pytest.raises(ConfigError):
        config.with_overrides({"model": {"variance": {"category_corr": {"XYZ": {"PTS": 0.1}}}}})


def test_calibrate_variance_script(tmp_path, config, logs):
    from calibrate_variance import main

    from fdo.ingest import load_dataset
    from fdo.ingest.synthetic import write_synthetic

    paths = write_synthetic(tmp_path, 260, 3, config, "2026-10-01")
    ds, _ = load_dataset(paths["players"], paths["projections"], paths["adp"], config=config)
    proj = ds.projections.head(30)
    gl = synthetic_gamelogs(proj, 30, np.random.default_rng(1), season="2025-26")
    gl.loc[len(gl)] = {**gl.iloc[0].to_dict(), "player_id": "", "name": "Unknown Player"}   # eşleşmeyen satır
    gl_path = tmp_path / "gamelogs_test.csv"
    gl.to_csv(gl_path, index=False)
    (tmp_path / "manifests" / "gamelogs_test.csv.yaml").write_text(yaml.safe_dump({
        "kind": "gamelogs", "source_name": "synthetic", "retrieved_at": "2026-10-13",
        "license_status": "personal_use_confirmed", "is_synthetic": True}), encoding="utf-8")
    assert main(["--gamelogs", str(gl_path), "--data", str(tmp_path), "--min-games", "10",
                 "--report", str(tmp_path / "rep")]) == 0
    var_csv = tmp_path / "variance_test.csv"
    ds2, rep = load_dataset(paths["players"], paths["projections"], paths["adp"], var_csv, config=config)
    assert rep.ok and ds2.variance is not None and ds2.variance["player_id"].nunique() == 30
    assert "category_corr" in (tmp_path / "rep" / "variance_calibration.md").read_text(encoding="utf-8")
    assert pd.read_csv(var_csv)["per_game_var"].gt(0).any()
