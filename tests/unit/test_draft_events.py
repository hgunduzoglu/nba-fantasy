import datetime as dt
import json

import pytest

from fdo.draft.events import DraftError, DraftLog, DraftPick
from fdo.draft.io import export_csv, export_json, import_log
from fdo.draft.state import state_from_log

T0 = dt.datetime(2026, 10, 20, 20, 0, 0)
IDS = [f"p_{i:04d}" for i in range(1, 260)]


def full_log(config, n):
    log = DraftLog.new(config)
    for i in range(n):
        log = log.make_pick(IDS[i], "manual", observed_at=T0)
    return log


def test_make_pick_assigns_round_and_seat(config):
    log = full_log(config, 17)
    assert [p.seat for p in log.picks[14:17]] == [15, 16, 16]
    assert log.picks[16].round == 2
    assert log.next_pick == 18 and log.next_seat == 15


def test_same_player_twice_is_error(config):
    log = full_log(config, 3)
    with pytest.raises(DraftError):
        log.make_pick(IDS[0])


def test_inconsistent_seat_is_error(config):
    log = DraftLog.new(config)
    with pytest.raises(DraftError):
        log.append(DraftPick(1, 1, 2, IDS[0], "import", T0))


def test_undo_and_replay_give_same_state(config):
    log = full_log(config, 40)
    s_full = state_from_log(log, config, IDS)
    undone = log.undo().undo().undo()
    redone = undone
    for p in log.picks[37:]:
        redone = redone.append(p)
    assert redone == log
    assert state_from_log(redone, config, IDS) == s_full
    replayed = DraftLog.replay(16, 13, False, log.picks)
    assert state_from_log(replayed, config, IDS) == s_full


def test_truncate_goes_back_to_pick(config):
    log = full_log(config, 40)
    t = log.truncate(20)
    assert t.next_pick == 20 and len(t) == 19
    assert t.picks == log.picks[:19]


def test_state_contents(config):
    log = full_log(config, 18)
    st = state_from_log(log, config, IDS)
    assert st.current_pick == 19
    assert st.rosters[16] == (IDS[15], IDS[16])
    assert st.rosters[15] == (IDS[14], IDS[17])
    assert st.remaining_picks[16][0] == 48
    assert len(st.remaining_picks[16]) == 11
    assert IDS[0] not in st.available and IDS[18] in st.available


def test_full_draft_completes(config):
    log = full_log(config, 208)
    assert log.is_complete and log.next_seat is None
    with pytest.raises(DraftError):
        log.make_pick(IDS[220])


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_export_import_roundtrip(config, fmt):
    log = full_log(config, 25)
    meta = {"seed": 42, "sources": [{"kind": "adp", "source_name": "synthetic"}]}
    text = export_csv(log, meta) if fmt == "csv" else export_json(log, meta)
    back, m = import_log(text, config)
    assert back == log
    assert m["seed"] == 42


def test_import_with_bad_seat_is_error(config):
    log = full_log(config, 5)
    data = json.loads(export_json(log))
    data["picks"][2]["seat"] = 9
    with pytest.raises(DraftError):
        import_log(json.dumps(data), config)


def test_import_rejects_config_mismatch(config, config_3rr):
    text = export_json(full_log(config, 3))
    with pytest.raises(DraftError):
        import_log(text, config_3rr)
