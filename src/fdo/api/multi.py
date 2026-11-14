"""Çok takımlı takas uç noktaları: elle analiz, sezon etkisi ve döngü önerileri."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from fdo.api.schemas import MultiSeasonIn, MultiSuggestIn, MultiTradeIn, StrategyIn
from fdo.api.serialize import (assumed_strategies, brief, category_deltas, clean, fixture_changes, games_delta,
                               strategy_from)
from fdo.api.state import AppState
from fdo.trade import Strategy, TradeError
from fdo.trade.data import MODES
from fdo.trade.multi import (SHAPES, MultiSearchOptions, MultiTradeRequest, analyze_multi, resolve_multi,
                             suggest_multi, value_flow)
from fdo.trade.perception import perceived_prices
from fdo.trade.strategy import CATEGORIES
from fdo.types import CATEGORY_LABELS


def _request(body: MultiTradeIn) -> MultiTradeRequest:
    return MultiTradeRequest(tuple((m.player, m.from_team, m.to_team) for m in body.moves),
                             tuple((t, p) for t, ps in body.drops.items() for p in ps),
                             tuple((t, p) for t, ps in body.adds.items() for p in ps), body.auto_balance)


def _strategy(s: StrategyIn | None, eng, team: str) -> Strategy:
    return strategy_from(s.model_dump() if s else None, eng, team)


def register(app: FastAPI, state: AppState) -> None:
    def engine(lid: str, injuries: bool):
        try:
            return state.engine(lid, injuries)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    def setup(lid: str, body: MultiTradeIn):
        eng = engine(lid, body.injuries)
        req = _request(body)
        for t in req.teams:
            if t not in eng.league.rosters:
                raise HTTPException(404, f"Takım yok: {t}")
        try:
            strategies = {t: _strategy(body.strategies.get(t), eng, t) for t in req.teams}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return eng, req, strategies

    @app.post("/api/leagues/{lid}/trade/multi/analyze")
    def analyze(lid: str, body: MultiTradeIn):
        eng, req, strategies = setup(lid, body)
        try:
            r = analyze_multi(eng, req, strategies)
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        names, teams = eng.data.players["name"], eng.league.teams
        perceived = value_flow(eng, req, perceived_prices(eng, "blend"))
        po = state.playoff_games(lid, body.injuries)
        out = []
        for t in r.teams:
            m = r.metrics.loc[t]
            before, after = r.profiles[t]
            out.append({
                "team_id": t, "team": teams[t], "strategy": r.strategies[t].name,
                **{k: float(m[k]) for k in ("ecw_before", "ecw_after", "ecw_delta", "win_before", "win_after",
                                             "win_delta", "strategy_before", "strategy_after", "strategy_delta",
                                             "value_in", "value_out")},
                "perceived_in": perceived[t][0], "perceived_out": perceived[t][1],
                "playoff_games": games_delta(po, eng.league.rosters[t], r.rosters_after[t]),
                "sent": [{**brief(eng, p), "to": d, "to_name": teams[d]} for p, s, d in req.moves if s == t],
                "received": [{**brief(eng, p), "from": s, "from_name": teams[s]} for p, s, d in req.moves if d == t],
                "categories": [{"key": c, "label": CATEGORY_LABELS[c], "before": float(x), "after": float(y)}
                               for c, x, y in zip(CATEGORIES, before, after)],
                "adjustments": {k: [{"id": p, "name": names[p]} for p in v] for k, v in r.adjustments[t].items()},
                "ranks": {mode: [{"key": c, "label": CATEGORY_LABELS[c],
                                  "value_before": r.before[mode].totals.loc[t, c],
                                  "value_after": r.after[mode].totals.loc[t, c],
                                  "rank_before": r.before[mode].ranks.loc[t, c],
                                  "rank_after": r.after[mode].ranks.loc[t, c]} for c in CATEGORIES]
                          for mode in MODES},
            })
        return clean({"teams": out, "fairness": r.fairness, "mutual": r.mutual, "assessments": r.assessments,
                      "notes": r.notes, "modes": MODES, "n_teams": len(r.teams)})

    @app.post("/api/leagues/{lid}/trade/multi/season")
    def season(lid: str, body: MultiSeasonIn):
        eng, req, strategies = setup(lid, body)
        sim = state.season_sim(lid, body.injuries)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok; sezon simülasyonu yapılamıyor.")
        n, sd = max(200, min(body.n_sims, 10_000)), max(0.0, min(body.strength_sd, 0.3))
        try:
            rosters, _, il = resolve_multi(eng, req, strategies)
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        first = tuple(req.teams)
        base = state.season_base(lid, body.injuries, n, sd, first=first)
        after = sim.run(rosters, n_sims=n, seed=1, strength_sd=sd, injuries=il, first=first)
        out = []
        for t in req.teams:
            b, a = base.table.loc[t], after.table.loc[t]
            out.append({"team_id": t, "team": eng.league.teams[t], "playoff_before": b.p_playoff,
                        "playoff_after": a.p_playoff, "champion_before": b.p_champion, "champion_after": a.p_champion,
                        "seed_before": b.mean_seed, "seed_after": a.mean_seed})
        return clean({"n_sims": n, "strength_sd": sd, "teams": out, "notes": after.notes})

    @app.post("/api/leagues/{lid}/trade/multi/fixtures")
    def fixtures(lid: str, body: MultiTradeIn):
        eng, req, strategies = setup(lid, body)
        sim = state.season_sim(lid, body.injuries)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok.")
        try:
            rosters, _, il = resolve_multi(eng, req, strategies)
        except (TradeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        return clean({"teams": fixture_changes(sim, req.teams, rosters, il)})

    @app.post("/api/leagues/{lid}/trade/multi/suggest")
    def suggest(lid: str, body: MultiSuggestIn):
        eng = engine(lid, body.injuries)
        if body.team not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {body.team}")
        opps = tuple(t for t in (body.opponents or eng.team_ids) if t != body.team)
        try:
            shapes = tuple(tuple(int(x) for x in s.split("-")) for s in body.shapes)
            opts = MultiSearchOptions(shapes, body.shortlist, min(body.shortlist4, body.shortlist),
                                      min_fairness=body.min_fairness, min_strategy_gain=body.min_gain,
                                      min_win_gain=body.min_win / 100, ecw_weight=body.ecw_weight,
                                      min_opponent_view=body.min_view)
            strategy = _strategy(body.strategy, eng, body.team)
            found = suggest_multi(eng, body.team, strategy=strategy,
                                  opponent_strategies=assumed_strategies(eng, body.opponent_assumption, opps),
                                  opponents=opps, options=opts)
        except (ValueError, TradeError) as e:
            raise HTTPException(400, str(e)) from e
        names, teams = eng.data.players["name"], eng.league.teams
        po = state.playoff_games(lid, body.injuries)
        rows = []
        for s in found.suggestions:
            req = s.request
            rosters, adj, il = resolve_multi(eng, req, s.strategies)
            p, _ = eng.score_many(rosters, s.strategies, il)
            flow = value_flow(eng, req)
            rows.append({
                "shape": "-".join(map(str, s.shape)), "shape_label": SHAPES[s.shape], "score": s.score,
                "fairness": s.fairness,
                "moves": [{"player": brief(eng, pl), "from": a, "from_name": teams[a], "to": b, "to_name": teams[b]}
                          for pl, a, b in req.moves],
                "teams": [{"team_id": t, "team": teams[t], "strategy": s.strategies[t].name,
                           "weights": list(s.strategies[t].weights), "strategy_delta": s.metrics[t]["strategy_delta"],
                           "win_delta": s.metrics[t]["win_delta"], "ecw_delta": s.metrics[t]["ecw_delta"],
                           "value_in": flow[t][0], "value_out": flow[t][1],
                           "playoff_games": games_delta(po, eng.league.rosters[t], rosters[t]),
                           "categories": category_deltas(eng, p, t, s.strategies),
                           "adjustments": {k: [names[x] for x in v] for k, v in adj[t].items()}}
                          for t in req.teams],
            })
        return clean({"suggestions": rows, "strategy": {"name": strategy.name, "weights": list(strategy.weights)},
                      "scanned": found.scanned, "candidates": found.candidates, "evaluated": found.evaluated,
                      "eligible": found.eligible, "rejected_view": found.rejected_view, "message": found.message,
                      "shapes": {"-".join(map(str, k)): v for k, v in SHAPES.items()}})
