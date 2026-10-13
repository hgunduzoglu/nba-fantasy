import pytest

from fdo.advisor.background import AnalysisWorker
from fdo.advisor.simulate import prepare_context
from fdo.bots.mock import MockDraft


@pytest.fixture(scope="module")
def ctx(synthetic_ds, universe, config):
    cfg = config.with_overrides({"model": {"advisor": {
        "fill_sims_conditional": 10, "sims_per_pair_fast": 8, "sims_per_pair": 12, "m_pairs_to_rollout": 3}}})
    return prepare_context(synthetic_ds, cfg, seed=3, universe=universe, fill_sims=20)


def test_worker_computes_board_advice_and_punt(ctx, synthetic_ds):
    m = MockDraft(synthetic_ds, ctx.config, seed=4, universe=ctx.universe)
    m.play_until_user()
    w = AnalysisWorker(punt_sims=3, board_sims=8)
    w.publish(ctx, m.log, live=True, seat_names={1: "A"})
    assert w.wait_idle(240)
    s = w.snapshot()
    assert s.board is not None and s.board.on_clock
    assert s.fast is not None and s.full is not None and s.advice is s.full
    assert s.full.params["mode"] == "full" and s.full.params["opponent_model"]
    assert s.opponents is not None and s.punt is not None and not s.errors
    rev = s.rev
    w.publish(ctx, m.log, live=True, seat_names={1: "A"})          # aynı durum: iş yok
    assert w.wait_idle(5) and w.snapshot().rev == rev


def test_worker_restarts_on_new_state_and_weights(ctx, synthetic_ds):
    m = MockDraft(synthetic_ds, ctx.config, seed=4, universe=ctx.universe)
    w = AnalysisWorker(full=False, punt_sims=0, board_sims=4)
    m.play_next()
    w.publish(ctx, m.log, live=False)
    m.play_until_user()
    w.publish(ctx, m.log, live=False)
    assert w.wait_idle(240)
    s = w.snapshot()
    assert s.job.log is m.log and s.fast is not None and s.full is None and s.opponents is None
    w.set_weights({c: (0.0 if c == "FT_PCT" else 1.0) for c in ctx.config.categories})
    assert w.wait_idle(240)
    s = w.snapshot()
    assert s.fast.params["category_weights"]["FT_PCT"] == 0.0 and w.weights["FT_PCT"] == 0.0
