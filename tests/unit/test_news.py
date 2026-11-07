"""Haber analizi: CBS ayrıştırma, zaman, süzme, partiler hâlinde analiz (sahte istemci), önbellek ve maliyet."""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from fdo.inseason import news as N

NOW = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.timezone.utc)
CBS_PAGE = """<ul id="playerNewsContent">
<li>
  <div class="row"><div class="players-annotated">
    <p><a href="/nba/players/1/ann-a/fantasy/">Ann A</a> <span> PG | AAA</span></p></div>
    <time class="eyebrow">2H ago</time>
    <h4><a href="/fantasy/basketball/news/ann-out/">Team's Ann A: Ruled out Sunday</a></h4>
    <div class="latest-updates"><p>Ann A (knee) won't play &amp; Bob B should start.</p></div>
  </div>
</li>
<li>
  <div class="row"><div class="players-annotated">
    <p><a href="/nba/players/2/bob-b/fantasy/">Bob B</a> <span> C | BBB</span></p></div>
    <time class="eyebrow">Nov 6</time>
    <h4><a href="/fantasy/basketball/news/bob-scores/">Team's Bob B: Scores 30 in loss</a></h4>
    <div class="latest-updates"><p>Bob B had 30 points.</p></div>
  </div>
</li>
</ul>"""
PLAYERS = pd.DataFrame({"name": ["Ann A", "Bob B", "Cy Cee"], "nba_team": ["AAA", "BBB", "CCC"],
                        "yahoo_positions": "PG", "injury_status": ""}, index=pd.Index(["1", "2", "3"], name="player_id"))


def test_parse_cbs_and_times():
    items = N.parse_cbs(CBS_PAGE, NOW)
    assert [i["player_name"] for i in items] == ["Ann A", "Bob B"] and items[0]["player_team"] == "AAA"
    assert items[0]["url"] == "https://www.cbssports.com/fantasy/basketball/news/ann-out/"
    assert items[0]["body"] == "Ann A (knee) won't play & Bob B should start."
    assert items[0]["published"] == "2026-11-08T10:00+00:00" and items[1]["published"].startswith("2026-11-06")
    assert N.published_at("15M ago", NOW) == "2026-11-08T11:45+00:00" and N.published_at("?", NOW) == ""
    assert N.published_at("Dec 30", dt.datetime(2027, 1, 2, tzinfo=dt.timezone.utc)).startswith("2026-12-30")


def test_relevance_filter_skips_recaps_and_unknown_players():
    from fdo.inseason.roles import resolver

    res = resolver(PLAYERS)
    names = {"ann a", "bob b", "cy cee"}
    ann, bob = N.parse_cbs(CBS_PAGE, NOW)
    assert N.relevant(ann, res, names) and not N.relevant(bob, res, names)          # maç özeti
    espn = {"source": "espn", "headline": "Trade talk: Cy Cee to the East?", "body": ""}
    assert N.relevant(espn, res, names)
    assert not N.relevant({**espn, "headline": "League sets record attendance"}, res, names)


class FakeClient:
    """``client.beta.messages.create`` → her habere bir olay (``fail`` partide reddeder)."""

    def __init__(self, fail_first: bool = False):
        self.calls, self.fail_first = [], fail_first
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        rows = json.loads(kw["messages"][0]["content"])
        refuse = self.fail_first and len(self.calls) == 1
        events = [{"id": r["id"], "player": r["player"], "team": r["team"], "type": "injury", "status": "out",
                   "return_estimate": "", "games_out": 1, "beneficiaries": ["Cy Cee"], "hurt": [], "impact": -1,
                   "summary_tr": f"{r['player']} yok"} for r in rows]
        usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        return SimpleNamespace(model=kw["model"], usage=usage, stop_reason="refusal" if refuse else "end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps({"events": events}))])


def _fetch():
    return N.parse_cbs(CBS_PAGE, NOW), ["CBS injury 1: HTTP 406"]


def test_refresh_analyzes_only_new_relevant_items_once(tmp_path):
    client = FakeClient()
    res = N.refresh(tmp_path, PLAYERS, fetch=_fetch, client=client)
    assert (res["new"], res["pending"], res["analyzed"]) == (2, 1, 1) and res["notes"] == ["CBS injury 1: HTTP 406"]
    call = client.calls[0]
    assert call["model"] == N.MODEL and call["fallbacks"] == "default"
    assert call["output_config"]["effort"] == "low" and call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    store = N.load_store(tmp_path)
    ann = store["items"]["https://www.cbssports.com/fantasy/basketball/news/ann-out/"]
    assert ann["analysis"]["summary_tr"] == "Ann A yok" and store["usage"][0]["input"] == 1000
    bob = store["items"]["https://www.cbssports.com/fantasy/basketball/news/bob-scores/"]
    assert bob["analysis"] is None and bob["skipped"]
    again = N.refresh(tmp_path, PLAYERS, fetch=_fetch, client=client)
    assert again["new"] == 0 and again["analyzed"] == 0 and len(client.calls) == 1   # bir kez analiz
    assert N.cost(store["usage"]) == pytest.approx((1000 * 4 + 500 * 20) / 1e6)


def test_refused_batch_is_retried_next_time(tmp_path):
    client = FakeClient(fail_first=True)
    assert N.refresh(tmp_path, PLAYERS, fetch=_fetch, client=client)["analyzed"] == 0
    assert N.refresh(tmp_path, PLAYERS, fetch=_fetch, client=client)["analyzed"] == 1


def test_without_key_items_are_kept_for_later(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "load_env_key", lambda: False)
    res = N.refresh(tmp_path, PLAYERS, fetch=_fetch)
    assert res["analyzed"] == 0 and any("ANTHROPIC_API_KEY" in n for n in res["notes"])
    assert len(N.load_store(tmp_path)["items"]) == 2


def test_old_items_are_pruned():
    store = {"items": {"a": {"published": "2026-10-01T00:00+00:00", "fetched_at": "x"},
                       "b": {"published": "2026-11-07T00:00+00:00", "fetched_at": "x"}}}
    N.prune(store, NOW)
    assert list(store["items"]) == ["b"]
