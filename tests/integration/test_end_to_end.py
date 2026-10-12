"""Uçtan uca: yükle → değerle → tam mock → advisor (hızlı) → export → import → aynı state (§9.2)."""

import pytest

from fdo.advisor.pairs import recommend
from fdo.advisor.simulate import prepare_context
from fdo.bots.mock import MockDraft
from fdo.draft.io import export_csv, export_json, import_log
from fdo.draft.state import state_from_log
from fdo.ingest import load_dataset
from fdo.ingest.synthetic import write_synthetic
from fdo.valuation import value_players


def run_pipeline(tmp_path, config, *, expect_turn, expect_next):
    paths = write_synthetic(tmp_path, 400, seed=7, config=config, as_of="2026-10-01")
    ds, report = load_dataset(paths["players"], paths["projections"], paths["adp"], config=config)
    assert ds is not None, report.errors
    val = value_players(ds.projections, config)
    assert val.table["rank"].min() == 1

    ctx = prepare_context(ds, config, seed=11, fill_sims=30)
    mock = MockDraft(ds, config, seed=3, universe=ctx.universe)
    mock.play_until_user()
    res = recommend(ctx, mock.log, n_sims=30)
    assert res.turn == expect_turn and res.next_turn == expect_next
    assert len(res.pairs) >= 5
    best = res.pairs[0]
    for pid in best.players:
        mock.pick(pid, "user")
    mock.play_to_end()
    assert mock.log.is_complete

    meta = {"seed": 3, "sources": ds.sources()}
    state = state_from_log(mock.log, config, ds.draft_ids)
    for text in (export_csv(mock.log, meta), export_json(mock.log, meta)):
        back, m = import_log(text, config)
        assert back == mock.log
        assert state_from_log(back, config, ds.draft_ids) == state
        assert m["sources"][0]["source_name"] == "synthetic"
    return ds, mock


def test_end_to_end_synthetic(tmp_path, config):
    run_pipeline(tmp_path, config, expect_turn=(16, 17), expect_next=(48, 49))


def test_end_to_end_with_third_round_reversal(tmp_path, config_3rr):
    ds, mock = run_pipeline(tmp_path, config_3rr, expect_turn=(16, 17), expect_next=(33,))
    seats = [p.seat for p in mock.log.picks]
    assert seats[32] == 16 and seats[47] == 1 and seats[48] == 1


@pytest.mark.slow
def test_single_pick_turn_in_3rr(tmp_path, config_3rr):
    paths = write_synthetic(tmp_path, 400, seed=7, config=config_3rr, as_of="2026-10-01")
    ds, _ = load_dataset(paths["players"], paths["projections"], paths["adp"], config=config_3rr)
    ctx = prepare_context(ds, config_3rr, seed=1, fill_sims=20)
    mock = MockDraft(ds, config_3rr, seed=3, universe=ctx.universe)
    while mock.log.next_pick < 33:
        mock.play_next()
    res = recommend(ctx, mock.log, n_sims=20)
    assert res.turn == (33,) and res.next_turn == (64, 65)
    assert all(len(p.players) == 1 for p in res.pairs)
