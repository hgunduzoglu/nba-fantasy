"""Takas için detaylı analiz uç noktaları (README §13.29): veri paketi, arka planda Claude, durum sorgusu.

Yerelde ``.env``'deki anahtarla açıktır. Salt okunur sunucuda yalnız ``FDO_REPORT_CODE`` ayarlıysa ve istek
``X-Report-Code`` başlığıyla aynı kodu gönderirse çalışır (adres herkese açık; ücretli çağrı korunur).
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException

from fdo.api.app import REPORT_CODE_ENV, _request, _strategies, scenario_rows
from fdo.api.schemas import ReportIn
from fdo.api.serialize import clean
from fdo.api.state import AppState
from fdo.inseason import news
from fdo.inseason.roles import load_logs
from fdo.inseason.trade_report import ReportStore, available, build_packet, report_key
from fdo.trade import TradeError
from fdo.trade.perception import perceived_prices
from fdo.trade.suggest import CompleteOptions, complete_trade


def register(app: FastAPI, state: AppState, engine, *, read_only: bool = False) -> ReportStore:
    store = ReportStore(state.data_dir)

    def access(code: str | None) -> None:
        if not available():
            raise HTTPException(503, "ANTHROPIC_API_KEY yok: detaylı analiz kapalı.")
        if read_only:
            expected = os.environ.get(REPORT_CODE_ENV, "").strip()
            if not expected:
                raise HTTPException(403, "Bu sunucuda detaylı analiz kapalı.")
            if (code or "").strip() != expected:
                raise HTTPException(401, "Detaylı analiz için erişim kodu gerekli.")

    def counters(lid: str, body: ReportIn, eng, sa, sb) -> list[dict]:
        """Karşı teklif adayları: en zayıf gelen oyuncu yerine (ya da iki tarafa) bir oyuncu ekleyerek; Yahoo ve bu
        sezonki oranlarla."""
        ga, gb = tuple(body.give_a), tuple(body.give_b)
        if len(ga) > 3 or len(gb) > 3:
            return []
        fixed_b = gb
        if len(gb) >= 2:
            weakest = min(gb, key=lambda p: float(eng.market.get(p, 0.0)))
            fixed_b = tuple(p for p in gb if p != weakest)
        # eşikler teklifin kendisine göre: rakip bu dengede teklif ettiyse benzer dengedeki seçenekler de gerçekçidir
        perceived = perceived_prices(eng, "blend")
        taken = float(perceived.reindex(list(gb)).fillna(0).sum())
        view = float(perceived.reindex(list(ga)).fillna(0).sum()) / taken if taken > 0 else 0.0
        fair = max(eng.fairness(_request(body)), min(view, 1 / view) if view > 0 else 0.0)   # complete_trade ile aynı
        opts = CompleteOptions(max_extra=1, max_results=8, auto_balance=body.auto_balance,
                               min_fairness=min(0.55, 0.9 * fair), min_view=min(0.8, 0.9 * view))
        try:
            found = complete_trade(eng, body.team_a, body.team_b, ga, fixed_b, strategy_a=sa, strategy_b=sb,
                                   options=opts)
        except (TradeError, ValueError):
            return []
        names = eng.data.players["name"]
        es = engine(lid, body.injuries, "season")
        ssa, ssb = _strategies(es, body)
        rows = []
        for s in found.suggestions[:8]:
            q = s.request
            try:
                season = float(es.analyze(q, strategy_a=ssa, strategy_b=ssb).metrics.loc[body.team_a, "ecw_delta"])
            except (TradeError, ValueError):
                season = None
            rows.append({"give_ids": list(q.give_a), "get_ids": list(q.give_b),
                         "give": [names[p] for p in q.give_a], "get": [names[p] for p in q.give_b],
                         "tier": s.mode, "your_delta_yahoo": round(s.own_strategy_delta, 3),
                         "their_delta_yahoo": round(s.other_strategy_delta, 3),
                         "your_ecw_delta_this_season_rates": None if season is None else round(season, 3),
                         "value_balance": round(s.fairness, 2), "their_view": round(s.perceived_balance, 2)})
        return rows

    def decorate(record: dict) -> dict:
        """Karşı tekliflere ad ekler; kadroda olmayan kimlikleri atar (``valid``: iki taraf da geçerli)."""
        rep = record.get("report")
        if not rep or "league" not in record:
            return record
        try:
            eng = engine(record["league"], True)
        except HTTPException:
            return record
        P, ros = eng.data.players, eng.league.rosters
        a, b = record.get("team_a"), record.get("team_b")
        for c in rep.get("counter_offers", []):
            c["give"] = [{"id": p, "name": P.loc[p, "name"]} for p in c.get("give_ids", []) if p in P.index]
            c["get"] = [{"id": p, "name": P.loc[p, "name"]} for p in c.get("get_ids", []) if p in P.index]
            c["valid"] = (bool(c["give"]) and bool(c["get"]) and {x["id"] for x in c["give"]} <= set(ros.get(a, ()))
                          and {x["id"] for x in c["get"]} <= set(ros.get(b, ())))
        return record

    @app.post("/api/leagues/{lid}/trade/report")
    def trade_report(lid: str, body: ReportIn, x_report_code: str | None = Header(default=None)):
        access(x_report_code)
        if not body.give_a or not body.give_b:
            raise HTTPException(400, "Detaylı analiz için iki taraftan da oyuncu seç.")
        eng = engine(lid, body.injuries)
        key = report_key(eng.data.fingerprint, lid, body.model_dump())
        got = store.get(key)
        if got and (got["status"] == "running" or not body.refresh):
            return clean(decorate(got))
        sa, sb = _strategies(eng, body)
        try:
            eng.resolve(_request(body), {body.team_a: sa, body.team_b: sb})
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        bases, _ = scenario_rows(lambda b: engine(lid, body.injuries, b), body)
        season = next(iter(eng.data.leagues.values())).config.league.season
        lv = state.live(lid, body.injuries)
        packet = build_packet(eng, body.team_a, body.team_b, body.give_a, body.give_b, strategies=(sa, sb),
                              scenarios=bases, counters=counters(lid, body, eng, sa, sb),
                              logs=load_logs(state.data_dir, season), news_store=news.load_store(state.data_dir),
                              playoff_games=state.playoff_games(lid, body.injuries),
                              live_adds_left=lv.adds_left(body.team_a, 7) if lv else None)
        names = eng.data.players["name"]
        meta = {"league": lid, "team_a": body.team_a, "team_b": body.team_b,
                "trade": {"give": [names[p] for p in body.give_a], "get": [names[p] for p in body.give_b],
                          "opponent": eng.league.teams[body.team_b]}}
        return clean(store.start(key, packet, meta))

    @app.get("/api/trade/report/{key}")
    def trade_report_status(key: str, x_report_code: str | None = Header(default=None)):
        access(x_report_code)
        got = store.get(key)
        if got is None:
            raise HTTPException(404, "Rapor bulunamadı.")
        return clean(decorate(got))

    return store
