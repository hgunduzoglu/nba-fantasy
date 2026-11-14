"""Teklif kayıtları ve cevaplar: birleştirme ve gruplu kabul oranı."""
from fdo.evaluation.offers import acceptance, offers


def _offer(i, level, view, lid="L"):
    return {"kind": "user_reported", "action": "trade_offer", "decision_id": f"o{i}", "created_at": f"t{i}",
            "league_id": lid, "request": {"team_b": "2", "give_a": ["1"], "give_b": ["9"]},
            "result": {"names": {}, "features": {"acceptability": level, "perceived_view": view}}}


def _answer(about, outcome):
    return {"kind": "user_reported", "action": "offer_response", "decision_id": f"r{about}{outcome}",
            "created_at": "t9", "league_id": "L", "request": {"about": about, "outcome": outcome}, "result": {}}


def test_offers_take_the_last_answer_and_group_acceptance():
    entries = [_offer(1, "high", 1.0), _offer(2, "medium", .9), _offer(3, "high", 1.3), _offer(4, "low", None, "M"),
               _answer("o1", "rejected"), _answer("o1", "accepted"), _answer("o2", "rejected"),
               {"kind": "scenario", "action": "trade_analyze"}]
    rows = offers(entries, "L")
    assert [(r["decision_id"], r["outcome"]) for r in rows] == [("o1", "accepted"), ("o2", "rejected"), ("o3", "pending")]
    acc = acceptance(rows)
    assert {g["group"]: (g["accepted"], g["n"]) for g in acc["acceptability"]} == {"high": (1, 1), "medium": (0, 1)}
    assert {g["group"] for g in acc["perceived_view"]} == {"0.95–1.10", "0.80–0.95"}
    assert len(offers(entries)) == 4
