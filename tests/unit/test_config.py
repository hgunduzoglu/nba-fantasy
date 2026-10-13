import pytest

from fdo.config import ConfigError, load_config


def test_default_config_loads(config):
    assert config.league.teams == 16
    assert config.league.rounds == 13
    assert config.league.total_picks == 208
    assert config.roster.size == 13
    assert config.roster.n_active == 10
    assert config.lower_is_better == frozenset({"TOV"})
    assert config.pool_size == 208
    assert "FC" not in config.roster.slots
    assert config.roster.slots["C"] == 2


def test_slots_must_sum_to_rounds(config):
    with pytest.raises(ConfigError):
        config.with_overrides({"league": {"rounds": 14}})


def test_bot_mix_must_cover_opponents(config):
    with pytest.raises(ConfigError):
        config.with_overrides({"model": {"bots": {"mix": {"MarketFollower": 3}}}})


def test_unverified_nulls_are_reported(config):
    assert config.unverified.null_fields() == []
    assert config.unverified.playoff_weeks == 3 and config.schedule.merge_with_next == (18,)
    un = config.unverified
    assert un.position_limits_enforced_in_draft is True
    assert (un.lineup_lock, un.il_slots, un.il_plus_slots) == ("daily_today", 3, 0)
    nulls = config.with_overrides({"unverified": {"lineup_lock": None}}).unverified.null_fields()
    assert nulls == ["lineup_lock"]


def test_invalid_lineup_lock_rejected(config):
    with pytest.raises(ConfigError):
        config.with_overrides({"unverified": {"lineup_lock": "monthly"}})


def test_overrides_change_hash(config, config_3rr):
    assert config_3rr.league.third_round_reversal is True
    assert config.config_hash != config_3rr.config_hash
    assert load_config().config_hash == config.config_hash


def test_league_14_config():
    from fdo.config import DEFAULT_CONFIG_DIR, league_files

    c = load_config(DEFAULT_CONFIG_DIR / "league_14.yaml")
    assert (c.league.teams, c.league.my_seat, c.league.total_picks) == (14, 9, 182)
    assert c.roster.slots["FC"] == 1 and c.roster.slots["C"] == 1 and c.roster.size == 13
    assert "FC" in c.roster.active_slots and sum(c.model.bots.mix.values()) == 13
    assert c.model.bots.sigma1 == load_config().model.bots.sigma1          # ortak model parametreleri
    assert DEFAULT_CONFIG_DIR / "league_14.yaml" in league_files()


def test_league_14_mock_draft(synthetic_ds):
    from fdo.bots.mock import MockDraft
    from fdo.config import DEFAULT_CONFIG_DIR

    c = load_config(DEFAULT_CONFIG_DIR / "league_14.yaml")
    m = MockDraft(synthetic_ds, c, 3)
    m.play_to_end()
    assert len(m.log) == 182
