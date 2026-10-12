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
    nulls = config.unverified.null_fields()
    assert "lineup_lock" in nulls
    assert "pick_timer_seconds" not in nulls and "tie_value" not in nulls
    assert config.unverified.position_limits_enforced_in_draft is True


def test_overrides_change_hash(config, config_3rr):
    assert config_3rr.league.third_round_reversal is True
    assert config.config_hash != config_3rr.config_hash
    assert load_config().config_hash == config.config_hash
