import datetime as dt
import shutil

import numpy as np
import pandas as pd
import pytest
import yaml

from fdo.config import AdpFallbackParams
from fdo.ingest import load_dataset
from fdo.ingest.adp_fallback import IsotonicMap, apply_adp_fallback, pav_increasing
from fdo.ingest.load import normalize_name, resolve_player_ids
from fdo.ingest.synthetic import write_synthetic
from fdo.ingest.validate import ValidationReport

AS_OF = "2026-10-01"
REF = dt.date(2026, 10, 5)


@pytest.fixture(scope="module")
def synth_dir(tmp_path_factory, config):
    d = tmp_path_factory.mktemp("synth")
    write_synthetic(d, 120, seed=11, config=config, as_of=AS_OF)
    return d


@pytest.fixture
def files(synth_dir, tmp_path):
    shutil.copytree(synth_dir, tmp_path, dirs_exist_ok=True)
    return {k: tmp_path / f"{k}_synthetic.csv" for k in ("players", "projections", "adp")}


def load(files, config, **kw):
    return load_dataset(files["players"], files["projections"], files["adp"], config=config,
                        reference_date=REF, **kw)


def edit(path, fn):
    df = pd.read_csv(path, dtype=str)
    df = fn(df)
    df.to_csv(path, index=False)


def test_clean_synthetic_loads(files, config):
    ds, rep = load(files, config)
    assert rep.ok, rep.errors
    assert ds.is_synthetic
    assert set(ds.adp.columns) >= {"adp_eff", "adp_status", "sigma_mult"}
    assert ds.adp["adp_eff"].notna().all()
    assert len(ds.content_hash) == 16


def test_missing_required_column_is_error(files, config):
    edit(files["projections"], lambda d: d.drop(columns=["reb"]))
    ds, rep = load(files, config)
    assert ds is None
    assert any("zorunlu kolon eksik" in e for e in rep.errors)


def test_unparseable_type_is_error(files, config):
    edit(files["projections"], lambda d: d.assign(pts=["abc"] + list(d["pts"][1:])))
    ds, rep = load(files, config)
    assert ds is None and any("sayıya" in e for e in rep.errors)


def test_fgm_gt_fga_is_error_but_zero_fga_ok(files, config):
    def zero(d):
        d.loc[0, ["fga", "fgm", "fg3m"]] = "0"
        d.loc[0, "pts"] = str(float(d.loc[0, "ftm"]))
        return d
    edit(files["projections"], zero)
    ds, rep = load(files, config)
    assert rep.ok, rep.errors
    assert any("fga=0" in n for n in rep.notes)

    def bad(d):
        d.loc[1, "fgm"] = str(float(d.loc[1, "fga"]) + 1)
        return d
    edit(files["projections"], bad)
    ds, rep = load(files, config)
    assert ds is None and any("fgm > fga" in e for e in rep.errors)


def test_duplicate_player_id_is_error(files, config):
    edit(files["players"], lambda d: pd.concat([d, d.iloc[[0]]]))
    ds, rep = load(files, config)
    assert ds is None and any("tekrarlanan player_id" in e for e in rep.errors)


def test_synthetic_real_mix_is_error(files, config):
    edit(files["adp"], lambda d: d.assign(is_synthetic="false"))
    ds, rep = load(files, config)
    assert ds is None and any("karıştırılamaz" in e for e in rep.errors)


def test_missing_manifest_not_loaded(files, config):
    (files["adp"].parent / "manifests" / f"{files['adp'].name}.yaml").unlink()
    ds, rep = load(files, config)
    assert ds is None and any("manifest yok" in e for e in rep.errors)


def test_unknown_license_warns(files, config):
    mpath = files["adp"].parent / "manifests" / f"{files['adp'].name}.yaml"
    m = yaml.safe_load(mpath.read_text(encoding="utf-8"))
    m["license_status"] = "unknown"
    mpath.write_text(yaml.safe_dump(m), encoding="utf-8")
    ds, rep = load(files, config)
    assert ds is not None and any("unknown" in w for w in rep.warnings)


def test_missing_stat_excludes_player(files, config):
    edit(files["projections"], lambda d: d.assign(blk=[None] + list(d["blk"][1:])))
    ds, rep = load(files, config)
    assert rep.ok
    pid = pd.read_csv(files["projections"])["player_id"][0]
    assert pid in rep.excluded
    assert pid not in ds.projected_ids


def test_bad_position_is_error(files, config):
    edit(files["players"], lambda d: d.assign(yahoo_positions=["XX"] + list(d["yahoo_positions"][1:])))
    ds, rep = load(files, config)
    assert ds is None and any("yahoo_positions" in e for e in rep.errors)


def test_fg_pct_column_mapping(files, config):
    def to_pct(d):
        fgm = d["fgm"].astype(float)
        fga = d["fga"].astype(float)
        d["FG%"] = np.where(fga > 0, fgm / fga, 0)
        return d.drop(columns=["fgm"])
    edit(files["projections"], to_pct)
    ds, rep = load(files, config)
    assert rep.ok, rep.errors
    assert any("fg_pct" in n for n in rep.notes)


# --- ADP fallback ---------------------------------------------------------

def _fallback_input():
    ids = [f"p{i}" for i in range(1, 11)]
    adp = pd.DataFrame({"player_id": ids,
                        "adp": [1, 2, 4, 3, 5, 6, 8, np.nan, 30, np.nan],
                        "pct_drafted": [99, 99, 99, 99, 99, 99, 99, np.nan, 20, np.nan]})
    vrank = pd.Series(range(1, 11), index=ids, dtype=float)
    return ids, adp, vrank


def test_missing_adp_is_imputed_and_low_pct_is_low_confidence():
    ids, adp, vrank = _fallback_input()
    params = AdpFallbackParams()
    tab, _ = apply_adp_fallback(ids, adp, vrank, params, pool_size=9)
    assert tab.loc["p8", "adp_status"] == "imputed"
    assert tab.loc["p10", "adp_status"] == "tail"
    assert tab.loc["p9", "adp_status"] == "low_confidence"
    w = 20 / 50
    expect = w * 30 + (1 - w) * tab.loc["p9", "adp_hat"]
    assert tab.loc["p9", "adp_eff"] == pytest.approx(expect)
    assert tab.loc["p9", "sigma_mult"] == 1.5
    assert tab.loc["p8", "sigma_mult"] == 2.0
    assert tab.loc["p10", "adp_eff"] > tab.drop(index="p10")["adp_eff"].max()


def test_after_coverage_places_unlisted_players_after_listed_in_value_order():
    ids = [f"p{i}" for i in range(1, 9)]
    # ADP kaynağı yalnızca ilk 5'i listeliyor; listelenmeyenlerin değer sırası 2, 6, 7
    adp = pd.DataFrame({"player_id": ids, "adp": [1, np.nan, 2, 3, 4, np.nan, np.nan, 5.0],
                        "pct_drafted": 99.0})
    vrank = pd.Series([1, 2, 3, 4, 5, 6, 7, 8], index=ids, dtype=float)
    tab, _ = apply_adp_fallback(ids, adp, vrank, AdpFallbackParams(), pool_size=6)
    assert tab.loc[["p2", "p6", "p7"], "adp_eff"].tolist() == [6.0, 7.0, 8.0]
    assert tab.loc[["p2", "p6", "p7"], "adp_status"].tolist() == ["imputed", "imputed", "tail"]
    # k. en küçük efektif ADP ≈ k (kapsam içine sıkışma yok)
    assert np.sort(tab["adp_eff"].to_numpy()).tolist() == [1, 2, 3, 4, 5, 6, 7, 8]


def test_isotonic_policy_still_available():
    ids, adp, vrank = _fallback_input()
    params = AdpFallbackParams(missing_adp_policy="isotonic")
    tab, _ = apply_adp_fallback(ids, adp, vrank, params, pool_size=9)
    assert tab.loc["p8", "adp_eff"] == pytest.approx(tab.loc["p8", "adp_hat"])


def test_low_confidence_without_pct_uses_half_weight():
    ids = ["a", "b", "c", "d"]
    adp = pd.DataFrame({"player_id": ids, "adp": [1.0, 2.0, 3.0, 200.0], "pct_drafted": np.nan})
    vrank = pd.Series([1.0, 2.0, 3.0, 4.0], index=ids)
    tab, _ = apply_adp_fallback(ids, adp, vrank, AdpFallbackParams(), pool_size=10)
    assert tab.loc["d", "adp_status"] == "low_confidence"
    assert tab.loc["d", "adp_eff"] == pytest.approx(0.5 * 200 + 0.5 * tab.loc["d", "adp_hat"])


def test_isotonic_is_monotone():
    rng = np.random.default_rng(0)
    x = np.arange(1, 201, dtype=float)
    y = x + rng.normal(0, 15, 200)
    fit = pav_increasing(y)
    assert np.all(np.diff(fit) >= -1e-12)
    iso = IsotonicMap.fit(x, y)
    grid = np.linspace(-10, 400, 500)
    assert np.all(np.diff(iso(grid)) >= -1e-12)
    assert iso(np.array([300.0]))[0] > iso(np.array([200.0]))[0]


# --- ad eşleme ------------------------------------------------------------

def test_name_normalization():
    assert normalize_name("Nikola Jokić") == normalize_name("nikola jokic")
    assert normalize_name("Jaren Jackson Jr.") == "jaren jackson"
    assert normalize_name("Shaq O'Neal III") == normalize_name("shaq o neal")


def _players():
    return pd.DataFrame({"player_id": ["p1", "p2", "p3", "p4"],
                         "name": ["Luka Dončić", "Jalen Williams", "Jalen Williams", "Bob Smith"],
                         "aliases": [None, None, None, "Bobby Smith;B. Smith"]})


def test_accented_and_plain_names_match():
    rep = ValidationReport()
    df = pd.DataFrame({"name": ["Luka Doncic", "Bobby Smith"]})
    out = resolve_player_ids(df, _players(), "t", rep)
    assert out["player_id"].tolist() == ["p1", "p4"]
    assert rep.ok


def test_ambiguous_name_is_error():
    rep = ValidationReport()
    df = pd.DataFrame({"name": ["Jalen Williams", "Nobody Here"]})
    resolve_player_ids(df, _players(), "t", rep)
    assert len(rep.errors) == 2
    assert {i["problem"] for i in rep.name_issues} == {"belirsiz", "eşleşmedi"}
