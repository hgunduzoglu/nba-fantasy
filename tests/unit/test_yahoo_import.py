import pytest

from fdo.ingest import build_dataset
from fdo.ingest.yahoo import convert, initial_key, parse_position_text


def _player(pid, name, team, pos, rank, gp=70, complete=True):
    stats = dict(fgm=350, fga=700, ftm=140, fta=175, three_pm=70, pts=910, reb=350, ast=210,
                 stl=70, blk=35, tov=140) if complete else {k: None for k in (
                     "fgm", "fga", "ftm", "fta", "three_pm", "pts", "reb", "ast", "stl", "blk", "tov")}
    return dict(player_id=pid, name=name, team=team, positions=pos, gp=gp if complete else None,
                preseason_rank=rank, current_rank=rank, rostered_pct=50, fg_pct=None, ft_pct=None,
                projection_complete=complete, **stats)


def _adp(pid, name, team, pos_text, xrank, adp=None, pct=None):
    return dict(player_id=pid, name=name, team=team, position_text=pos_text, xrank=xrank,
                drafted_pct=pct, adp_preseason=adp, adp_all=adp, adp_last7=None)


@pytest.fixture
def jsons():
    P = {"source": "Yahoo Fantasy Basketball", "stats_mode": "S_PSR", "extracted_at": "2026-10-12T19:33:43Z",
         "season_totals": [
             _player("1", "S. Gilgeous-Alexander", "OKC", ["PG"], 1),
             _player("2", "Luka Dončić", "LAL", ["PG", "SG"], 2, gp=35),
             _player(None, "", "UTA", ["C"], 3, complete=False),
             _player(None, "J. Doe", "BOS", ["SF"], 4),
         ]}
    A = {"source": "Yahoo Draft Analysis", "extracted_at": "2026-10-12T19:27:34Z", "players": [
        _adp("1", "Shai Gilgeous-Alexander", "OKC", "OKC - PG Q", 1, 1.5, 100),
        _adp("2", "Luka Dončić", "LAL", "LAL - PG,SG O", 2, 3.4, 100),
        _adp("9", "Jonas Aidoo", "UTA", "UTA - C NA", 3),
        _adp("7", "John Doe", "BOS", "BOS - SF", 99),
    ]}
    return P, A


def test_parse_position_text():
    assert parse_position_text("DET - PG,SG Q") == ("PG,SG", "Q")
    assert parse_position_text("SAS - C") == ("C", "")


def test_initial_key_matches_abbreviation():
    assert initial_key("S. Gilgeous-Alexander", "OKC") == initial_key("Shai Gilgeous-Alexander", "OKC")


def test_convert_matches_by_id_rank_and_initials(jsons):
    players, proj, adp, log = convert(*jsons)
    assert list(players["player_id"]) == ["y_1", "y_2", "y_9", "y_7"]
    assert "player_id=2" in log[0] and "takım+pozisyon+sıra=1" in log[0] and "baş harf+takım=1" in log[0]
    # tam ad ADP dosyasından, kısaltma alias olarak
    assert players.loc[0, "name"] == "Shai Gilgeous-Alexander"
    assert players.loc[0, "aliases"] == "S. Gilgeous-Alexander"
    assert players.loc[1, "yahoo_positions"] == "PG,SG"
    assert list(players["injury_status"]) == ["Q", "O", "NA", ""]
    # projeksiyon: toplam / gp; eksik projeksiyon yazılmaz
    assert set(proj["player_id"]) == {"y_1", "y_2", "y_7"}
    luka = proj.set_index("player_id").loc["y_2"]
    assert luka["projected_gp"] == 35 and luka["pts"] == pytest.approx(910 / 35, abs=1e-4)
    assert proj.set_index("player_id").loc["y_1", "notes"] == "Yahoo durum: Q"
    a = adp.set_index("player_id")
    assert a.loc["y_1", "adp"] == 1.5 and a.loc["y_1", "default_rank"] == 1
    assert a["adp"].isna().sum() == 2


def test_converted_tables_validate(jsons, config):
    players, proj, adp, _ = convert(*jsons)
    ds, rep = build_dataset(players, proj, adp, config)
    assert rep.ok, rep.errors
    assert not ds.is_synthetic
    assert "y_9" in rep.excluded          # projeksiyon ve ADP yok


def test_out_factor_applies_only_to_out_players(jsons, config):
    from fdo.availability import effective_projections
    from fdo.matchup.player_week import per_game_variance, weekly_vectors

    players, proj, adp, _ = convert(*jsons)
    ds, rep = build_dataset(players, proj, adp, config)
    assert any("Out durumundaki 1 oyuncu" in n for n in rep.notes)
    eff = effective_projections(ds.projections, config).set_index("player_id")["projected_gp"]
    f = config.model.availability.out_gp_factor
    assert eff["y_2"] == pytest.approx(35 * f)     # O
    assert eff["y_1"] == 70 and eff["y_7"] == 70   # Q ve durumsuz etkilenmez
    off = config.with_overrides({"model": {"availability": {"out_gp_factor": 1.0}}})
    var, _ = per_game_variance(ds.projections, None, {})
    on_w, off_w = weekly_vectors(ds.projections, var, config), weekly_vectors(ds.projections, var, off)
    assert on_w.loc["y_2", 1] == pytest.approx(off_w.loc["y_2", 1] * f)
    assert on_w.loc["y_1", 1] == pytest.approx(off_w.loc["y_1", 1])
