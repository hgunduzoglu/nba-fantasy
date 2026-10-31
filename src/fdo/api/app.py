"""FastAPI uygulaması: ``/api/*`` uç noktaları ve derlenmiş React arayüzü (``frontend/dist``)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fdo.api.serialize import (categories_meta, clean, player_row, presets, strategy_from, trade_result,
                               value_ranks)
from fdo.api.schemas import SeasonIn, TradeIn
from fdo.api.state import SOURCES, AppState
from fdo.config import REPO_ROOT
from fdo.trade import TradeError, TradeRequest
from fdo.trade.perception import perceived_prices

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


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


def create_app(data_dir: str | Path | None = None, frontend_dir: str | Path | None = None) -> FastAPI:
    state = AppState(data_dir)
    app = FastAPI(title="Fantasy Trade Lab", version="1.0")
    app.state.fdo = state
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def engine(lid: str, injuries: bool):
        try:
            return state.engine(lid, injuries)
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
                      "issues": list(data.issues)})

    @app.get("/api/leagues/{lid}/roster/{tid}")
    def roster(lid: str, tid: str, source: str = Query("ros", pattern="^(ros|season|preseason)$"),
               injuries: bool = True):
        eng = engine(lid, injuries)
        if tid not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {tid}")
        z = state.per_game_z(lid, source, injuries)
        ranks = value_ranks(eng)
        il = eng.league.injury_rosters[tid]
        players = [player_row(eng, p, source, z, il=il, ranks=ranks) for p in eng.league.rosters[tid]]
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
        return {"source": source, "players": [player_row(eng, p, source, z, ranks=ranks) for p in fa]}

    @app.post("/api/leagues/{lid}/trade/analyze")
    def analyze(lid: str, body: TradeIn):
        eng = engine(lid, body.injuries)
        try:
            sa, sb = _strategies(eng, body)
            result = eng.analyze(_request(body), strategy_a=sa, strategy_b=sb)
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        return trade_result(eng, result, perceived=perceived_prices(eng, "blend"))

    @app.post("/api/leagues/{lid}/trade/season")
    def trade_season(lid: str, body: SeasonIn):
        eng = engine(lid, body.injuries)
        sim = state.season_sim(lid, body.injuries)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok; sezon simülasyonu yapılamıyor.")
        n, sd = max(200, min(body.n_sims, 10_000)), max(0.0, min(body.strength_sd, 0.3))
        try:
            sa, sb = _strategies(eng, body)
            rosters, _, _ = eng.resolve(_request(body), {body.team_a: sa, body.team_b: sb})
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        base = state.season_base(lid, body.injuries, n, sd)
        after = sim.run(rosters, n_sims=n, seed=1, strength_sd=sd)
        out = {}
        for side, tid in (("a", body.team_a), ("b", body.team_b)):
            b, a = base.table.loc[tid], after.table.loc[tid]
            out[side] = {"team_id": tid, "playoff_before": b.p_playoff, "playoff_after": a.p_playoff,
                         "champion_before": b.p_champion, "champion_after": a.p_champion,
                         "seed_before": b.mean_seed, "seed_after": a.mean_seed}
        return clean({"n_sims": n, "strength_sd": sd, "teams": out, "notes": after.notes})

    @app.get("/api/sources")
    def sources():
        return SOURCES

    from fdo.api import inseason, multi
    inseason.register(app, state)
    multi.register(app, state)

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
