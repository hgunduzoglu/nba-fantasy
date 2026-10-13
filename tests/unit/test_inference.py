import numpy as np
import pytest

from fdo.bots.inference import ProfileTracker, mix_prior
from fdo.bots.mock import MockDraft
from fdo.bots.thurstone import BatchDraft


@pytest.fixture(scope="module")
def drafted(synthetic_ds, universe, config):
    m = MockDraft(synthetic_ds, config, seed=21, universe=universe)
    m.play_to_end()
    return m


def test_true_profiles_gain_posterior_mass(drafted, universe, config):
    tr = ProfileTracker(universe, config, n_draws=100, seed=3)
    model = tr.update(drafted.log)
    post, prior = model.posterior, model.prior
    names = list(model.names)
    gains = []
    for seat, prof in enumerate(drafted.profiles, start=1):
        if seat == config.league.my_seat:
            continue
        j = names.index(prof)
        gains.append(post[seat - 1, j] - prior[j])
    assert np.mean(gains) > 0.1                      # gerçek profil ortalamada belirgin kazanır
    assert np.allclose(post.sum(axis=1), 1.0)
    assert (post[:, names.index("AutoDrafter")] == 0).all()   # karışımda 0 → öncel 0
    t = model.table()
    assert len(t) == config.league.teams - 1 and {"en olası profil", "olası punt"} <= set(t.columns)


def test_incremental_matches_batch_and_undo_resets(drafted, universe, config):
    full = ProfileTracker(universe, config, n_draws=60, seed=1).update(drafted.log.truncate(60))
    tr = ProfileTracker(universe, config, n_draws=60, seed=1)
    tr.update(drafted.log.truncate(30))
    inc = tr.update(drafted.log.truncate(60))
    assert np.allclose(inc.loglik, full.loglik)
    back = tr.update(drafted.log.truncate(20))          # geri alma → baştan kurulur
    assert back.n_picks.sum() < inc.n_picks.sum()


def test_engine_uses_seat_profile_probs(universe, config):
    P = len(BatchDraft(universe, config, 1, 0).ptab.names)
    probs = np.zeros((config.league.teams, P))
    probs[:, 1] = 1.0                                    # herkes ValueHunter
    probs[config.league.my_seat - 1] = 0.0
    eng = BatchDraft(universe, config, 5, 0, seat_profile_probs=probs)
    others = np.delete(eng.profile, config.league.my_seat - 1, axis=1)
    assert (others == 1).all()


def test_mix_prior(config):
    names = ("MarketFollower", "ValueHunter", "PositionAware", "PuntBuilder", "AutoDrafter", "RandomHuman")
    p = mix_prior(config, names)
    assert p.sum() == pytest.approx(1.0) and p[4] == 0.0
