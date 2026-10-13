import pandas as pd

from fdo.calibration.bots import auto_mask, league_config, logs_to_matrix, survival_brier
from fdo.draft.io import import_names
from fdo.ingest.yahoo import flip_name, parse_results_text, results_from_json, snake_violations

TEXT = """Round 1
(1) Kyle - Jokić, Nikola (DEN - C)
(2) Team 2 - Wembanyama, Victor (SAS - C)
(3) Hüsamettin - Murphy III, Trey (NOP - SG,SF)


Round 2
(1) Hüsamettin - Porter Jr., Michael (BKN - SF,PF)
(2) Team 2 - Dončić, Luka (LAL - PG,SG)
(3) Kyle - Şengün, Alperen (HOU - C,PF)
"""


def test_flip_name():
    assert flip_name("Murphy III, Trey") == "Trey Murphy III"
    assert flip_name("Porter Jr., Michael") == "Michael Porter Jr."
    assert flip_name("Nene") == "Nene"


def test_parse_results_text_flags_and_snake():
    df = parse_results_text(TEXT, user_team="Hüsamettin")
    assert list(df["pick"]) == [1, 2, 3, 4, 5, 6]
    assert df.loc[0, "player"] == "Nikola Jokić" and df.loc[3, "player"] == "Michael Porter Jr."
    assert list(df["auto"]) == [False, True, False, False, True, False]
    assert list(df["user"]) == [False, False, True, True, False, False]
    assert snake_violations(df, 3) == []
    bad = df.copy()
    bad.loc[5, "fantasy_team"] = "Hüsamettin"            # 6. pick seat 1'in, Hüsamettin seat 3
    assert snake_violations(bad, 3)


def test_results_from_json():
    data = {"picks": [{"overall_pick": 2, "round": 1, "pick_in_round": 2, "player": "B", "nba_team": "X",
                       "positions": ["PG", "SG"], "fantasy_team": "Me"},
                      {"overall_pick": 1, "round": 1, "pick_in_round": 1, "player": "A", "nba_team": "Y",
                       "positions": ["C"], "fantasy_team": "Team 1"}]}
    df = results_from_json(data, user_team="Me")
    assert list(df["player"]) == ["A", "B"] and df.loc[1, "positions"] == "PG,SG"
    assert list(df["auto"]) == [True, False] and list(df["user"]) == [False, True]


def test_user_picks_excluded_and_brier(synthetic_ds, universe, config):
    c14 = league_config(config, 14)
    names = synthetic_ds.names()
    order = [str(universe.ids[i]) for i in universe.adp.argsort()][: 14 * 13]
    df = pd.DataFrame({"pick": range(1, len(order) + 1), "player": [names[p] for p in order],
                       "auto": [k % 7 == 0 for k in range(len(order))],
                       "user": [k % 14 == 8 for k in range(len(order))]})
    log, notes = import_names(df.to_csv(index=False), synthetic_ds.players, c14)
    assert sum(p.source == "import:user" for p in log.picks) == 13 and "13 kullanıcı" in notes[0]
    mask = auto_mask([log])
    assert mask.sum() == int((df["auto"] | df["user"]).sum())
    mat, _ = logs_to_matrix([log], universe)
    assert survival_brier(mat, mat, universe) == 0.0       # kendisini mükemmel tahmin eder


def test_infer_autopicks_runs():
    import numpy as np

    from fdo.calibration.bots import infer_autopicks

    df = pd.DataFrame({"fantasy_team": ["A", "B"] * 6})
    # A: T F T T T F  → 3'lü seri; B: T T F T T F → seri yok
    m = np.array([True, True, False, True, True, False, True, True, True, True, False, False])
    out = infer_autopicks(df, m, min_run=3)
    a = out[df["fantasy_team"] == "A"]
    b = out[df["fantasy_team"] == "B"]
    assert list(a) == [False, False, True, True, True, False] and not b.any()
    assert not infer_autopicks(df, m, min_run=4).any()
