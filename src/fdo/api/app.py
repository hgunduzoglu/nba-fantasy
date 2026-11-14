"""FastAPI uygulaması: ``/api/*`` uç noktaları ve derlenmiş React arayüzü (``frontend/dist``)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fdo.api.serialize import (brief, categories_meta, clean, fixture_changes, player_row, presets,
                               return_timeline, season_effect, strategy_from, trade_result, value_ranks)
from fdo.api.schemas import OfferIn, SeasonIn, SeasonManyIn, TradeIn
from fdo.api.state import SOURCES, AppState
from fdo.config import REPO_ROOT
from fdo.evaluation.decisions import reconcile
from fdo.evaluation.offers import offers as offer_rows
from fdo.ingest.freshness import report as freshness_report
from fdo.inseason.injuries import return_assumptions
from fdo.inseason.scenarios import BASES, RATE_BASES, per_game_rates
from fdo.trade import TradeError, TradeRequest
from fdo.trade.perception import perceived_prices
from fdo.trade.suggest import offer_features

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
#: Sunucu kurulumu (README §14.2): veri bilgisayardan gönderilir; Yahoo senkronizasyonu ve haber yenileme kapalı.
READ_ONLY_ENV = "FDO_READ_ONLY"
#: Salt okunur sunucuda detaylı analiz (ücretli) için erişim kodu; yoksa kapalı.
REPORT_CODE_ENV = "FDO_REPORT_CODE"


def read_only_env() -> bool:
    return os.environ.get(READ_ONLY_ENV, "").strip().lower() in ("1", "true", "yes", "on")



def report_status(read_only: bool) -> dict:
    """Detaylı analiz (README §13.29): anahtar var mı; salt okunur sunucuda erişim kodu gerekir."""
    from fdo.inseason.trade_report import available
    code = bool(os.environ.get(REPORT_CODE_ENV, "").strip())
    return {"available": available() and (not read_only or code), "needs_code": read_only and code}

def _request(t: TradeIn) -> TradeRequest:
    return TradeRequest(t.team_a, t.team_b, tuple(t.give_a), tuple(t.give_b), tuple(t.drop_a), tuple(t.drop_b),
                        tuple(t.add_a), tuple(t.add_b), t.auto_balance, t.auto_balance)


def _strategies(eng, body: TradeIn):
    """İki tarafın stratejisi (otomatik punt kendi takımının profilinden)."""
    for t in (body.team_a, body.team_b):
        if t not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {t}")
    return (strategy_from(body.strategy_a and body.strategy_a.model_dump(), eng, body.team_a),
            strategy_from(body.strategy_b and body.strategy_b.model_dump(), eng, body.team_b))


def scenario_rows(engine_for, body: TradeIn) -> tuple[list[dict], dict[str, dict]]:
    """Takası her istatistik temelinde değerlendirir (README §13.28). ``engine_for(basis)`` o temelin motorunu verir.
    Dönüş: temel başına iki tarafın farkları ve IL dönüş takvimi; oyuncu başına temellerdeki maç başı oranlar."""
    bases, players = [], {p: {} for p in [*body.give_a, *body.give_b]}
    late = return_assumptions()["late_days"]
    for basis, label in BASES.items():
        if basis == "late":
            label = f"{label} (+{late} gün)"
        eng = engine_for(basis)
        try:
            sa, sb = _strategies(eng, body)
            req = _request(body)
            result = eng.analyze(req, strategy_a=sa, strategy_b=sb)
            _, _, il = eng.resolve(req, {body.team_a: sa, body.team_b: sb})
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        side = {}
        for k, tid, st, inc in (("a", body.team_a, sa, body.give_b), ("b", body.team_b, sb, body.give_a)):
            m = result.metrics.loc[tid]
            side[k] = {"ecw_delta": m.ecw_delta, "win_delta": m.win_delta, "strategy_delta": m.strategy_delta,
                       "drops": [eng.data.players.loc[x, "name"] for x in result.adjustments[tid]["drop"]],
                       "returns": return_timeline(eng, result.rosters_after[tid], il[tid], st, inc)}
        bases.append({"basis": basis, "label": label, "fairness": result.assessments["fairness_ratio"],
                      "mutual": result.assessments["mutual_benefit"], **side})
        if basis in RATE_BASES:
            for x in players:
                players[x][basis] = per_game_rates(eng.data, x)
    return bases, players


def create_app(data_dir: str | Path | None = None, frontend_dir: str | Path | None = None, *,
               read_only: bool | None = None) -> FastAPI:
    """``read_only`` (varsayılan ``FDO_READ_ONLY`` ortam değişkeni): güncelleme uç noktaları 403 döner."""
    read_only = read_only_env() if read_only is None else read_only
    state = AppState(data_dir)
    app = FastAPI(title="Fantasy Trade Lab", version="1.0")
    app.state.fdo = state
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def engine(lid: str, injuries: bool, basis: str = "ros"):
        try:
            return state.engine(lid, injuries, basis)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/meta")
    def meta(injuries: bool = True):
        data = state.data(injuries)
        inj = state.injury_file()
        leagues = []
        for lid, lg in data.leagues.items():
            leagues.append({"id": lid, "name": lg.name, "default_team": lg.default_team_id,
                            "teams": [{"id": t, "name": n} for t, n in lg.teams.items()],
                            "capacity": lg.capacity, "il_slots": lg.config.unverified.il_slots,
                            "trade_deadline": lg.settings.get("Trade End Date"),
                            "playoffs": lg.settings.get("Playoffs")})
        return clean({"as_of": data.as_of, "leagues": leagues, "categories": categories_meta(),
                      "sources": {"ros": "Kalan sezon projeksiyonu", "season": "Bu sezon",
                                  "preseason": "Sezon öncesi projeksiyon"},
                      "presets": presets(), "injury_file": inj.name if inj else None,
                      "issues": list(data.issues), "read_only": read_only,
                      "report": report_status(read_only), "returns": return_assumptions()})

    @app.get("/api/leagues/{lid}/roster/{tid}")
    def roster(lid: str, tid: str, source: str = Query("ros", pattern="^(ros|season|preseason)$"),
               injuries: bool = True):
        eng = engine(lid, injuries)
        if tid not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {tid}")
        z = state.per_game_z(lid, source, injuries)
        ranks = value_ranks(eng)
        il = eng.league.injury_rosters[tid]
        perc = state.perceived(lid, source, injuries)
        players = [player_row(eng, p, source, z, il=il, ranks=ranks, perceived=perc) for p in eng.league.rosters[tid]]
        players.sort(key=lambda r: (r["il"], -(r["value"] or 0)))
        return {"team_id": tid, "team": eng.league.teams[tid], "source": source, "players": players}

    @app.get("/api/leagues/{lid}/free-agents")
    def free_agents(lid: str, source: str = Query("ros", pattern="^(ros|season|preseason)$"),
                    injuries: bool = True, limit: int = 150):
        eng = engine(lid, injuries)
        owned = {p for r in eng.league.rosters.values() for p in r}
        z = state.per_game_z(lid, source, injuries)
        ranks = value_ranks(eng)
        fa = sorted((p for p in eng.ids if p not in owned and eng.modeled[eng.index[p]]),
                    key=lambda p: -float(eng.market[p]))[:limit]
        perc = state.perceived(lid, source, injuries)
        return {"source": source, "players": [player_row(eng, p, source, z, ranks=ranks, perceived=perc) for p in fa]}

    @app.post("/api/leagues/{lid}/trade/analyze")
    def analyze(lid: str, body: TradeIn):
        eng = engine(lid, body.injuries, body.basis)
        try:
            sa, sb = _strategies(eng, body)
            result = eng.analyze(_request(body), strategy_a=sa, strategy_b=sb)
            _, _, il = eng.resolve(_request(body), {body.team_a: sa, body.team_b: sb})
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        out = trade_result(eng, result, perceived=perceived_prices(eng, "blend"))
        for side, tid, s, inc in (("a", body.team_a, sa, body.give_b), ("b", body.team_b, sb, body.give_a)):
            out["teams"][side]["returns"] = clean(return_timeline(eng, result.rosters_after[tid], il[tid], s, inc))
        out["basis"] = body.basis
        teams = {side: {k: t.get(k) for k in ("team_id", "strategy", "ecw_delta", "win_delta", "strategy_delta")}
                 for side, t in out["teams"].items()}
        out["decision_id"] = state.log_decision("scenario", "trade_analyze", lid, body.model_dump(),
                                                {"teams": teams, "fairness": out.get("fairness"),
                                                 "perceived_balance": out.get("perceived_balance")})
        return out

    @app.post("/api/leagues/{lid}/trade/reported")
    def trade_reported(lid: str, body: TradeIn):
        """Kullanıcı "bu takası yaptım" der: ``user_reported`` olarak günlüğe eklenir; veriyi değiştirmez, bir sonraki
        içe aktarmada kadrolarla karşılaştırılır (``GET`` aynı yol)."""
        eng = engine(lid, body.injuries)
        for tid in (body.team_a, body.team_b):
            if tid not in eng.league.teams:
                raise HTTPException(404, "Takım yok")
        if not body.give_a and not body.give_b:
            raise HTTPException(400, "Takasta oyuncu yok")
        names = {p: eng.data.players.loc[p, "name"] for p in [*body.give_a, *body.give_b] if p in eng.data.players.index}
        did = state.log_decision("user_reported", "trade_done", lid, body.model_dump(), {"names": names})
        if did is None:
            raise HTTPException(503, "Karar günlüğü kapalı ya da yazılamadı")
        return {"decision_id": did}

    @app.get("/api/leagues/{lid}/trade/reported")
    def trade_reported_list(lid: str, injuries: bool = True):
        """Bildirilen takaslar (en yeni önce) ve güncel kadrolara göre durumu: confirmed / partial / pending."""
        eng = engine(lid, injuries)
        rows = [e for e in state.decisions.entries("user_reported") if e["league_id"] == str(lid)]
        return [{"decision_id": e["decision_id"], "created_at": e["created_at"], "data_as_of": e["data_as_of"],
                 "team_a": e["request"]["team_a"], "team_b": e["request"]["team_b"],
                 "give_a": [{"id": p, "name": e["result"]["names"].get(p, p)} for p in e["request"]["give_a"]],
                 "give_b": [{"id": p, "name": e["result"]["names"].get(p, p)} for p in e["request"]["give_b"]],
                 "status": reconcile(e, eng.league.rosters)} for e in reversed(rows[-20:])]

    @app.post("/api/leagues/{lid}/trade/offer")
    def trade_offer(lid: str, body: OfferIn):
        """Teklif ettim (o anki ölçülerle) ya da teklife gelen cevap. Eşiklerin gerçek kayıtlarla ayarlanması için
        (``fdo.evaluation.offers``); veriyi değiştirmez."""
        eng = engine(lid, body.injuries)
        if body.outcome != "offered":
            known = {e["decision_id"] for e in state.decisions.entries("user_reported") if e["action"] == "trade_offer"}
            if body.about not in known:
                raise HTTPException(404, "Cevaplanan teklif kaydı yok")
            did = state.log_decision("user_reported", "offer_response", lid,
                                     {"about": body.about, "outcome": body.outcome}, {})
        else:
            sa, sb = _strategies(eng, body)
            try:
                features = offer_features(eng, _request(body), sa, sb, perceived_prices(eng, "blend"))
            except (TradeError, ValueError) as e:
                raise HTTPException(400, str(e)) from e
            names = {p: eng.data.players.loc[p, "name"] for p in [*body.give_a, *body.give_b]}
            did = state.log_decision("user_reported", "trade_offer", lid, body.model_dump(exclude={"outcome", "about"}),
                                     {"names": names, "features": features})
        if did is None:
            raise HTTPException(503, "Karar günlüğü kapalı ya da yazılamadı")
        return {"decision_id": did}

    @app.get("/api/leagues/{lid}/trade/offers")
    def trade_offers(lid: str):
        """Kaydedilen teklifler (en yeni önce), son cevaplarıyla ve o anki kabul gerekçesi düzeyiyle."""
        rows = offer_rows(state.decisions.entries("user_reported"), lid)
        return clean([{"decision_id": r["decision_id"], "created_at": r["created_at"], "outcome": r["outcome"],
                       "team_a": r["request"]["team_a"], "team_b": r["request"]["team_b"],
                       "give_a": [{"id": p, "name": r["names"].get(p, p)} for p in r["request"]["give_a"]],
                       "give_b": [{"id": p, "name": r["names"].get(p, p)} for p in r["request"]["give_b"]],
                       "acceptability": r["features"].get("acceptability"),
                       "perceived_view": r["features"].get("perceived_view")} for r in reversed(rows[-30:])])

    @app.post("/api/leagues/{lid}/trade/scenarios")
    def trade_scenarios(lid: str, body: TradeIn):
        """Aynı takas dört istatistik temelinde (README §13.28): Yahoo projeksiyonu, bu sezonki oranlar, son 10 maç,
        karma. Her temelde bütün lig o oranlarla değerlenir; IL dönüşünde takasla gelen oyuncunun bırakılıp
        bırakılmadığı da."""
        bases, players = scenario_rows(lambda b: engine(lid, body.injuries, b), body)
        eng = engine(lid, body.injuries)
        season = eng.data.stats["season_total"]
        return clean({"bases": bases, "players": [
            {**brief(eng, p), "side": "a" if p in body.give_a else "b",
             "season_gp": float(season.loc[p, "gp"]) if p in season.index else None, "rates": r}
            for p, r in players.items()]})

    @app.post("/api/leagues/{lid}/trade/season")
    def trade_season(lid: str, body: SeasonIn):
        eng = engine(lid, body.injuries, body.basis)
        sim = state.season_sim(lid, body.injuries, body.basis)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok; sezon simülasyonu yapılamıyor.")
        n, sd = max(200, min(body.n_sims, 10_000)), max(0.0, min(body.strength_sd, 0.3))
        try:
            sa, sb = _strategies(eng, body)
            rosters, _, il = eng.resolve(_request(body), {body.team_a: sa, body.team_b: sb})
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        base = state.season_base(lid, body.injuries, n, sd, basis=body.basis)
        after = sim.run(rosters, n_sims=n, seed=1, strength_sd=sd, injuries=il)
        out = {}
        for side, tid in (("a", body.team_a), ("b", body.team_b)):
            b, a = base.table.loc[tid], after.table.loc[tid]
            out[side] = {"team_id": tid, "playoff_before": b.p_playoff, "playoff_after": a.p_playoff,
                         "champion_before": b.p_champion, "champion_after": a.p_champion,
                         "seed_before": b.mean_seed, "seed_after": a.mean_seed,
                         "effect": season_effect(sim, base, after, tid)}
        return clean({"n_sims": n, "strength_sd": sd, "teams": out, "notes": after.notes})

    @app.post("/api/leagues/{lid}/trade/season/many")
    def trade_season_many(lid: str, body: SeasonManyIn):
        """Öneri listesindeki takasların sezon etkisi: iki takımın P(playoff), P(şampiyon) ve ortalama sıra farkı,
        takassız sezona göre aynı çekilişlerle (eşleşmeli) ve Monte Carlo standart hatasıyla. Sıralamayı değiştirmez;
        model puanının yanında gösterilir (gölge). Çözülemeyen takas ``error`` ile döner, diğerleri etkilenmez."""
        eng = engine(lid, body.injuries, body.basis)
        sim = state.season_sim(lid, body.injuries, body.basis)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok; sezon simülasyonu yapılamıyor.")
        n, sd = max(200, min(body.n_sims, 5000)), max(0.0, min(body.strength_sd, 0.3))
        base = state.season_base(lid, body.injuries, n, sd, basis=body.basis)
        rows = []
        for i, t in enumerate(body.trades):
            try:
                sa, sb = _strategies(eng, t)
                rosters, _, il = eng.resolve(_request(t), {t.team_a: sa, t.team_b: sb})
            except (TradeError, ValueError, HTTPException) as e:
                rows.append({"index": i, "error": getattr(e, "detail", None) or str(e)})
                continue
            after = sim.run(rosters, n_sims=n, seed=1, strength_sd=sd, injuries=il)
            rows.append({"index": i, "give_a": list(t.give_a), "give_b": list(t.give_b),
                         "teams": {side: {"team_id": tid, **season_effect(sim, base, after, tid)}
                                   for side, tid in (("a", t.team_a), ("b", t.team_b))}})
        out = clean({"n_sims": n, "strength_sd": sd, "trades": rows,
                     "notes": base.notes + ["Takas sonrası kadrolar sezon boyu sabit; fark kalan normal sezon ve playoff "
                                            "braketinin simülasyonundan. Hata payı yalnız simülasyon gürültüsü."]})
        summary = [{"give_a": r.get("give_a"), "give_b": r.get("give_b"), "error": r.get("error"),
                    "a": {k: v["delta"] for k, v in r["teams"]["a"].items() if isinstance(v, dict)}
                    if "teams" in r else None} for r in out["trades"]]
        state.log_decision("scenario", "trade_season_many", lid, body.model_dump(), {"n_sims": n, "trades": summary})
        return out

    @app.post("/api/leagues/{lid}/trade/fixtures")
    def trade_fixtures(lid: str, body: TradeIn):
        """Fikstürdeki her hafta için kazanma olasılığı: takassız / takaslı (iki taraf)."""
        eng = engine(lid, body.injuries, body.basis)
        sim = state.season_sim(lid, body.injuries, body.basis)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok.")
        try:
            sa, sb = _strategies(eng, body)
            rosters, _, il = eng.resolve(_request(body), {body.team_a: sa, body.team_b: sb})
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        return clean({"teams": fixture_changes(sim, (body.team_a, body.team_b), rosters, il)})

    @app.get("/api/sources")
    def sources():
        return SOURCES

    @app.get("/api/freshness")
    def freshness():
        """Bileşen bazında veri güncelliği ve karar türüne göre durum (normal / koşullu / bekletilir)."""
        data = state.data()
        season = next(iter(data.leagues.values())).config.league.season if data.leagues else None
        return clean(freshness_report(state.data_dir, season=season, read_only=read_only))

    from fdo.api import inseason, multi, news, sync
    inseason.register(app, state)
    multi.register(app, state)
    app.state.news = news.register(app, state, read_only=read_only)
    from fdo.api import report
    app.state.reports = report.register(app, state, engine, read_only=read_only)
    after = [lambda log: news.refresh_logs(state), lambda log: news.refresh_news(state, log)]
    app.state.sync = sync.register(app, state, sync.SyncJob(state, after=after), read_only=read_only)

    frontend = Path(frontend_dir) if frontend_dir else FRONTEND_DIST
    if (frontend / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        root = frontend.resolve()

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Bilinmeyen API yolu")
            target = (root / path).resolve()
            if path and target.is_file() and root in target.parents:
                return FileResponse(target)
            return FileResponse(root / "index.html")

    return app
