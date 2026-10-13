import time

import pytest

from fdo.draft.events import DraftLog
from fdo.yahoo_api import (
    AppCredentials,
    TokenProvider,
    TokenStore,
    YahooAuthError,
    YahooClient,
    merge,
    parse_draft_results,
)
from fdo.yahoo_api.client import player_id_from_key
from fdo.yahoo_api.oauth import Token, authorize_url, exchange_code

LEAGUE = "466.l.777"


def payload(picks: dict[int, str | None], teams: int = 16, rounds: int = 13, trr=False, team_of=None):
    """Yahoo JSON biçiminde draftresults; ``picks``: pick → oyuncu numarası (None = yapılmadı)."""
    from fdo.draft.order import pick_order

    order = pick_order(teams, rounds, trr)
    team_of = team_of or (lambda k: f"{LEAGUE}.t.{order[k - 1]}")
    res = {}
    for i, k in enumerate(sorted(picks)):
        r = {"pick": k, "round": (k - 1) // teams + 1, "team_key": team_of(k)}
        if picks[k] is not None:
            r["player_key"] = f"466.p.{picks[k]}"
        res[str(i)] = {"draft_result": r}
    res["count"] = len(picks)
    return {"fantasy_content": {"league": [[{"league_key": LEAGUE}, {"draft_status": "drafting"},
                                             {"num_teams": teams}], {"draft_results": res}]}}


@pytest.fixture
def known():
    return {f"y_{i}" for i in range(1, 400)}


def test_parse_draft_results():
    meta, res = parse_draft_results(payload({1: "5", 2: "7", 3: None}))
    assert meta["league_key"] == LEAGUE and meta["draft_status"] == "drafting"
    assert [r.pick for r in res] == [1, 2, 3] and res[2].player_key is None
    assert player_id_from_key(res[0].player_key) == "y_5"


def test_merge_appends_and_dedupes(config, known):
    log = DraftLog.new(config)
    _, res = parse_draft_results(payload({1: "1", 2: "2", 3: "3", 4: None}))
    log, rep = merge(log, res, known)
    assert rep.ok and rep.added == [1, 2, 3] and [p.player_id for p in log.picks] == ["y_1", "y_2", "y_3"]
    assert all(p.source == "import:yahoo_api" for p in log.picks)
    _, res = parse_draft_results(payload({1: "1", 2: "2", 3: "3", 4: "4"}))
    log, rep = merge(log, res, known)
    assert rep.added == [4] and rep.skipped == [1, 2, 3]


def test_gap_stops_merge(config, known):
    _, res = parse_draft_results(payload({1: "1", 2: None, 3: "3"}))
    log, rep = merge(DraftLog.new(config), res, known)
    assert rep.gaps == [2] and rep.added == [1] and len(log) == 1


def test_manual_pick_wins_conflict(config, known):
    log = DraftLog.new(config).make_pick("y_1", "manual").make_pick("y_9", "manual")
    _, res = parse_draft_results(payload({1: "1", 2: "2", 3: "3"}))
    out, rep = merge(log, res, known)
    assert rep.conflicts == [(2, "y_9", "y_2")] and out is log


def test_non_manual_conflict_rebuilds_from_api(config, known):
    log = DraftLog.new(config).make_pick("y_1", "import").make_pick("y_9", "import").make_pick("y_8", "import")
    _, res = parse_draft_results(payload({1: "1", 2: "2", 3: "3"}))
    out, rep = merge(log, res, known)
    assert rep.replaced_from == 2 and [p.player_id for p in out.picks] == ["y_1", "y_2", "y_3"]


def test_unknown_player_and_seat_mismatch(config, known):
    _, res = parse_draft_results(payload({1: "1", 2: "9999"}))
    log, rep = merge(DraftLog.new(config), res, known)
    assert not rep.ok and len(log) == 1 and "veri setinde yok" in rep.errors[0]
    # 3RR'li Yahoo sırası, 3RR'siz config: 33. pick seat 16 değil seat 1 (config) ...
    trr = payload({k: str(k) for k in range(1, 40)}, trr=True)
    _, res = parse_draft_results(trr)
    log, rep = merge(DraftLog.new(config), res, known)
    assert not rep.ok and "uyuşmuyor" in rep.errors[0] and len(log) == 0


def test_oauth_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("YAHOO_CLIENT_ID", "cid")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "sec")
    creds = AppCredentials.load(tmp_path / "none.json")
    assert "client_id=cid" in authorize_url(creds) and "redirect_uri=oob" in authorize_url(creds)
    calls = []

    def post(url, headers, form):
        calls.append(form)
        assert headers["Authorization"].startswith("Basic ")
        if form["grant_type"] == "authorization_code":
            return {"access_token": "A1", "refresh_token": "R1", "expires_in": 3600}
        return {"access_token": "A2", "expires_in": 3600}

    store = TokenStore(tmp_path / "tok.json")
    store.save(exchange_code(creds, " code123 ", post))
    assert calls[0]["code"] == "code123"
    prov = TokenProvider(creds, store, post)
    assert prov.access_token() == "A1"
    store.save(Token("A1", "R1", time.time() - 10))                 # süresi dolmuş
    assert prov.access_token() == "A2" and store.load().refresh_token == "R1"
    with pytest.raises(YahooAuthError):
        exchange_code(creds, "bad", lambda *a: {"error": "invalid_grant"})


def test_client_get_uses_bearer_and_json():
    seen = {}

    class FakeTokens:
        def access_token(self):
            return "TOKEN"

    def get(url, headers):
        seen.update(url=url, headers=headers)
        return payload({1: "1"})

    meta, res = YahooClient(FakeTokens(), get).draft_results(LEAGUE)
    assert seen["url"].endswith(f"league/{LEAGUE}/draftresults?format=json")
    assert seen["headers"]["Authorization"] == "Bearer TOKEN" and len(res) == 1
