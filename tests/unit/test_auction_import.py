import pandas as pd

from fdo.ingest.auction import parse_costs

PLAYERS = pd.DataFrame({"player_id": ["a", "b", "c"], "name": ["Nikola Jokić", "Trey Murphy III", "Bam Adebayo"]})


def test_parse_free_text_lines():
    text = "1. Nikola Jokic (DEN - C) $64.5\nMurphy III, Trey  NOP  SF,PF  $22\nNobody Here $3\n"
    s, miss = parse_costs(text, PLAYERS)
    assert s.to_dict() == {"a": 64.5, "b": 22.0} and miss == ["Nobody Here"]


def test_parse_csv_and_json():
    s, _ = parse_costs("Player,Avg Cost,% Drafted\nBam Adebayo,$18.3,95\n", PLAYERS)
    assert s.to_dict() == {"c": 18.3}
    s, _ = parse_costs('{"players": [{"name": "Nikola Jokić", "avg_cost": 61}]}', PLAYERS)
    assert s.to_dict() == {"a": 61.0}
