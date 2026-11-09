"""Oyuncu kimliği eşleştirme (``fdo.inseason.identity``): yalnız tek aday, karantina, elle düzeltme, rapor."""
import pandas as pd
import pytest

from fdo.inseason.identity import IdentityReport, Resolver, load_overrides

POOL = pd.DataFrame({"name": ["Nikola Jokić", "Jaren Jackson Jr.", "Jalen Williams", "Jalen Williams",
                              "N. Alexander-Walker", "Giannis Antetokounmpo", "Gary Trent Jr."],
                     "nba_team": ["DEN", "UTA", "OKC", "DEN", "ATL", "MIA", "MIL"]},
                    index=["1", "2", "3", "4", "5", "6", "7"])


def test_accents_suffixes_and_initials_match_one_player():
    r = Resolver(POOL)
    assert r("Nikola Jokic", "DEN").player_id == "1" and r("Nikola Jokic", "DEN").method == "name_team"
    assert r("Jaren Jackson", "UTA").player_id == "2"                      # Jr. yok sayılır
    m = r("Nickeil Alexander-Walker", "ATL")
    assert (m.player_id, m.method) == ("5", "initial_team")
    assert r("Gary Trent", "MIL").player_id == "7"


def test_same_name_needs_the_team_and_otherwise_is_quarantined():
    r = Resolver(POOL)
    assert r("Jalen Williams", "OKC").player_id == "3" and r("Jalen Williams", "DEN").player_id == "4"
    m = r("Jalen Williams", "LAL")
    assert m.status == "ambiguous" and m.player_id is None and set(m.candidates) == {"3", "4"}
    assert r("Jalen Williams").status == "ambiguous"


def test_team_change_matches_but_is_flagged_and_unknown_is_unmatched():
    r = Resolver(POOL)
    m = r("Giannis Antetokounmpo", "MIL")                                   # havuzda tek; takım değişmiş olabilir
    assert (m.player_id, m.method, m.team_mismatch) == ("6", "name", True)
    assert not r("Giannis Antetokounmpo", "MIA").team_mismatch
    assert r("Nobody Known", "MIA").status == "unmatched" and r("", "MIA").status == "unmatched"


def test_overrides_resolve_ambiguity_and_respect_the_source(tmp_path):
    (tmp_path / "id_overrides.csv").write_text(
        "source,name,nba_team,player_id,note\ncbs,Jalen Williams,LAL,4,elle doğrulandı\n,J. Williams,,3,her kaynak\n"
        ",Kimse,,999,havuzda yok\n", encoding="utf-8")
    ov = load_overrides(tmp_path)
    assert Resolver(POOL, ov, source="cbs")("Jalen Williams", "LAL").player_id == "4"
    assert Resolver(POOL, ov, source="nba")("Jalen Williams", "LAL").status == "ambiguous"   # başka kaynak
    assert Resolver(POOL, ov)("J. Williams", "OKC").method == "override"
    assert Resolver(POOL, ov)("Kimse").status == "unmatched"                 # havuzda olmayan kimlik kullanılmaz
    assert load_overrides(tmp_path / "yok") is None and load_overrides(None) is None
    (tmp_path / "id_overrides.csv").write_text("name\nx\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_overrides(tmp_path)


def test_report_counts_and_names_problem_rows():
    r, rep = Resolver(POOL), IdentityReport("Test kaynağı")
    for name, team in (("Nikola Jokic", "DEN"), ("Jalen Williams", "LAL"), ("Nobody", "ATL"),
                       ("Giannis Antetokounmpo", "MIL")):
        rep.add(f"{name} ({team})", r(name, team))
    assert (rep.rows, rep.matched, rep.by_method) == (4, 2, {"name_team": 1, "name": 1})
    note = rep.note()
    assert "eşleşmeyen 1 satır (Nobody (ATL))" in note and "belirsiz 1 satır" in note and "takımı farklı 1" in note
