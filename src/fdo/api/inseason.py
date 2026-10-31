"""Sezon içi uç noktalar: takas önerileri, yanlış fiyatlama, bu hafta + streaming, boştakiler, sezon, sıralamalar."""

from __future__ import annotations

import numpy as np
from fastapi import FastAPI, HTTPException, Query

from fdo.api.schemas import StrategyIn, StreamIn, SuggestIn, WaiverIn, WeeklyIn
from fdo.api.serialize import (assumed_strategies, brief, category_deltas, clean, games_delta, player_row,
                               strategy_from, value_ranks)
from fdo.api.state import AppState
from fdo.inseason.fixtures import opponent as fixture_opponent
from fdo.inseason.waiver import drop_ranking, waiver_table
from fdo.inseason.weekly import DEFAULT_OUT, Stint, WeekOutlook, acquisition_limit, vector_totals
from fdo.roster.assignment import best_assignment
from fdo.trade import Strategy, TradeError
from fdo.trade.data import MODES, ROS
from fdo.trade.perception import mispricing, perceived_prices
from fdo.trade.strategy import CATEGORIES
from fdo.trade.suggest import SearchOptions, suggest_trades
from fdo.types import CATEGORY_LABELS


def _strategy(s: StrategyIn | None, eng=None, team: str | None = None) -> Strategy:
    try:
        return strategy_from(s.model_dump() if s else None, eng, team)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


_brief = brief


def _outlook(eng, o: WeekOutlook) -> dict:
    tm, to = vector_totals(o.mine.vector), vector_totals(o.opp.vector)

    def grid(tw):
        rows = []
        for pid in tw.grid.index:
            rows.append({**_brief(eng, pid), "marks": list(tw.grid.loc[pid]), "counted": int(tw.counted.get(pid, 0))})
        return rows
    return {"p": list(o.p), "expected_wins": o.expected_wins, "p5": o.p5, "strategy_score": o.strategy_score,
            "totals": {"mine": tm, "opp": to},
            "counted": {"mine": int(o.mine.counted.sum()), "opp": int(o.opp.counted.sum())},
            "benched": {"mine": o.mine.benched, "opp": o.opp.benched},
            "day_labels": list(o.mine.grid.columns), "grid": {"mine": grid(o.mine), "opp": grid(o.opp)}}


def register(app: FastAPI, state: AppState) -> None:
    def engine(lid: str, injuries: bool):
        try:
            return state.engine(lid, injuries)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    def team_check(eng, tid: str) -> None:
        if tid not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {tid}")

    # ------------------------------------------------------------- takas önerileri
    @app.post("/api/leagues/{lid}/trade/suggest")
    def suggest(lid: str, body: SuggestIn):
        eng = engine(lid, body.injuries)
        team_check(eng, body.team)
        opps = tuple(t for t in (body.opponents or eng.team_ids) if t != body.team)
        opp_strats = assumed_strategies(eng, body.opponent_assumption, opps)
        try:
            sizes = tuple(tuple(int(x) for x in p.split("x")) for p in body.packages)
            opts = SearchOptions(sizes, body.shortlist, int(body.max_evaluations), 20, body.min_fairness,
                                 body.min_gain, body.min_win / 100, body.auto_balance, body.ecw_weight,
                                 body.mode, body.perceived, body.min_balance, body.min_edge,
                                 body.min_view if body.mode == "mutual" else 0.0)
            strategy = _strategy(body.strategy, eng, body.team)
            found = suggest_trades(eng, body.team, strategy=strategy, opponent_strategies=opp_strats,
                                   opponents=opps, options=opts)
        except (ValueError, TradeError) as e:
            raise HTTPException(400, str(e)) from e
        perceived = perceived_prices(eng, body.perceived)
        po_games = state.playoff_games(lid, body.injuries)
        rows = []
        for s in found.suggestions:
            r = s.request
            rosters, adj, il = eng.resolve(r, {body.team: strategy, r.team_b: s.other_strategy})
            p, _ = eng.score(rosters, body.team, r.team_b, strategy, s.other_strategy, il)
            taken = float(perceived.reindex(list(r.give_b)).fillna(0).sum())
            active = [x for x in rosters[body.team] if x not in il[body.team]]
            rows.append({"my_categories": category_deltas(eng, p, body.team, strategy),
                         "other_categories": category_deltas(eng, p, r.team_b, s.other_strategy),
                         "playoff_games": games_delta(po_games, eng.league.rosters[body.team], rosters[body.team]),
                         "position_gap": best_assignment(eng.positions(active), eng.config).n_open_active,
                         "perceived_view": float(perceived.reindex(list(r.give_a)).fillna(0).sum()) / taken
                         if taken > 0 else None,"team_b": r.team_b, "team_b_name": eng.league.teams[r.team_b],
                         "give_a": [_brief(eng, p) for p in r.give_a], "give_b": [_brief(eng, p) for p in r.give_b],
                         "own_delta": s.own_strategy_delta, "other_delta": s.other_strategy_delta,
                         "own_win": s.own_win_delta, "other_win": s.other_win_delta, "fairness": s.fairness,
                         "perceived_balance": s.perceived_balance, "score": s.score, "mode": s.mode,
                         "key_players": list(s.key_players), "other_strategy": s.other_strategy.name,
                         "other_weights": list(s.other_strategy.weights),
                         "adjustments": {t: {k: [eng.data.players.loc[p, "name"] for p in v] for k, v in a.items()}
                                         for t, a in adj.items()}})
        return clean({"suggestions": rows, "strategy": {"name": strategy.name, "weights": list(strategy.weights)},
                      "examined": found.examined, "eligible": found.eligible,
                      "rejected_balance": found.rejected_fairness, "rejected_view": found.rejected_view,
                      "rejected_roster": found.rejected_roster,
                      "limit_reached": found.limit_reached, "message": found.message})

    @app.get("/api/leagues/{lid}/trade/mispricing")
    def mispriced(lid: str, team: str, perceived: str = Query("blend", pattern="^(season_total|preseason|blend)$"),
                  injuries: bool = True):
        eng = engine(lid, injuries)
        team_check(eng, team)
        m = mispricing(eng, perceived_prices(eng, perceived))
        m = m.assign(team=[eng.league.teams[t] for t in m["team_id"]])
        cols = ["player_id", "name", "team_id", "team", "gp_now", "perceived_rank", "ros_rank", "edge"]
        return clean({"sell_high": m[m["team_id"] == team].head(12)[cols].to_dict("records"),
                      "buy_low": m[m["team_id"] != team].sort_values("edge").head(20)[cols].to_dict("records")})

    # ------------------------------------------------------------- bu hafta
    def _week_setup(lid: str, body: WeeklyIn):
        eng = engine(lid, body.injuries)
        team_check(eng, body.team)
        weeks = state.weeks(lid, body.injuries)
        as_of = eng.data.as_of
        current = weeks.week_of(as_of)
        if current is None:
            later = weeks.weeks.index[weeks.weeks["start"] > as_of]
            current = int(later.min()) if len(later) else int(weeks.weeks.index.max())
        wk = int(body.week or current)
        if wk not in weeks.weeks.index:
            raise HTTPException(400, f"Hafta yok: {wk}")
        days = weeks.days(wk, as_of if wk == current else None)
        fx_opp = fixture_opponent(state.fixtures(), lid, body.team, wk)
        opp = body.opponent or fx_opp or next(t for t in eng.team_ids if t != body.team)
        team_check(eng, opp)
        out = DEFAULT_OUT if body.sit_out else tuple(s for s in DEFAULT_OUT if s != "O")
        model = state.week_model(lid, body.injuries, _strategy(body.strategy, eng, body.team), out)
        return eng, weeks, current, wk, days, fx_opp, opp, model

    def _weeks_list(weeks, current):
        return [{"week": int(w), "start": r.start, "end": r.end, "playoff": bool(r.playoff), "current": int(w) == current}
                for w, r in weeks.weeks.iterrows() if int(w) >= current]

    @app.post("/api/leagues/{lid}/weekly")
    def weekly(lid: str, body: WeeklyIn):
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        o = model.outlook(body.team, opp, days, acc_mine=body.acc_mine, acc_opp=body.acc_opp, week=wk)
        drops = drop_ranking(eng, body.team, _strategy(body.strategy, eng, body.team))
        active = model.active_roster(body.team)
        ranked = [p for p in (list(drops["drop"]) if len(drops) else []) if p in active]
        cheapest = sorted(active, key=lambda p: float(eng.market.get(p, 0.0)))     # kalan sezon değeri en düşük
        default_drop = list(dict.fromkeys([*ranked, *cheapest]))[:3]
        return clean({"weeks": _weeks_list(weeks, current), "current_week": current, "week": wk,
                      "week_start": weeks.weeks.loc[wk, "start"], "days": days, "opponent": opp,
                      "opponent_name": eng.league.teams[opp], "fixture_opponent": fx_opp,
                      "started": wk == current and eng.data.as_of > weeks.weeks.loc[wk, "start"],
                      "acquisitions_limit": acquisition_limit(eng.league.settings),
                      "active_roster": [_brief(eng, p) for p in active], "default_droppable": default_drop,
                      "outlook": _outlook(eng, o), "notes": list(weeks.notes)})

    @app.post("/api/leagues/{lid}/weekly/stream")
    def stream(lid: str, body: StreamIn):
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        base = model.outlook(body.team, opp, days, acc_mine=body.acc_mine, acc_opp=body.acc_opp, week=wk)
        left = max(0, acquisition_limit(eng.league.settings) - int(body.used))
        s = model.stream(base, moves=left, droppable=list(body.droppable), acc_mine=body.acc_mine)
        moves = [{"day": m.day, "add": _brief(eng, m.add), "drop": _brief(eng, m.drop), "ros_delta": m.ros_delta,
                  "games": sum(model.has_game(m.add, d) for d in s.days if d >= m.day)} for m in s.moves]
        return clean({"moves": moves, "left": left, "before": {"p": list(base.p), "expected_wins": base.expected_wins,
                                                                "p5": base.p5},
                      "after": _outlook(eng, s)})

    # ------------------------------------------------------------- boştakiler
    @app.post("/api/leagues/{lid}/waiver")
    def waiver(lid: str, body: WaiverIn):
        team, injuries = body.team, body.injuries
        eng = engine(lid, injuries)
        team_check(eng, team)
        strategy = _strategy(body.strategy, eng, team)
        t = waiver_table(eng, team, strategy, top=body.top)
        weeks = state.weeks(lid, injuries)
        wk = weeks.week_of(eng.data.as_of)
        model = state.week_model(lid, injuries)
        this_days = weeks.days(wk, eng.data.as_of) if wk else []
        next_days = weeks.days(wk + 1) if wk and wk + 1 in weeks.weeks.index else []
        z = state.per_game_z(lid, "ros", injuries)
        ranks = value_ranks(eng)
        rows = []
        for r in t.itertuples():
            rows.append({"add": player_row(eng, r.add, "ros", z, ranks=ranks), "drop": _brief(eng, r.drop),
                         "score": r.score, "delta_ecw": r.delta_ecw,
                         "dp": {c: getattr(r, f"d_{c}") for c in CATEGORIES},
                         "games_this_week": sum(model.has_game(r.add, d) for d in this_days),
                         "games_next_week": sum(model.has_game(r.add, d) for d in next_days)})
        d = drop_ranking(eng, team, strategy)
        drops = [{"drop": _brief(eng, x.drop), "best_add": _brief(eng, x.add), "score": x.score}
                 for x in d.itertuples()] if len(d) else []
        return clean({"rows": rows, "drops": drops, "days_this_week": len(this_days), "week": wk})

    # ------------------------------------------------------------- sezon
    @app.get("/api/leagues/{lid}/season")
    def season(lid: str, team: str, n: int = 2000, sd: float = 0.06, injuries: bool = True):
        eng = engine(lid, injuries)
        team_check(eng, team)
        sim = state.season_sim(lid, injuries)
        if sim is None:
            raise HTTPException(409, "Bu lig için fikstür yok; sezon simülasyonu yapılamıyor.")
        n, sd = max(200, min(n, 10_000)), max(0.0, min(sd, 0.3))
        res = sim.run(n_sims=n, seed=1, team=team, strength_sd=sd)
        t = res.table
        rounds = len(sim.playoff_weeks)
        byes = max(0, 2 ** rounds - res.playoff_size) if rounds else 0
        table = [{"team_id": tid, "team": r.team, "record_now": r.get("record_now", ""), "exp_w": r.exp_wins,
                  "exp_l": r.exp_losses, "exp_t": r.exp_ties, "exp_pct": r.exp_pct, "mean_seed": r.mean_seed,
                  "p_playoff": r.p_playoff, "p_bye": r.p_bye, "p_first": r.p_first, "p_champion": r.p_champion}
                 for tid, r in t.sort_values("mean_seed").iterrows()]
        sched = [{"week": int(r.week), "start": r.start, "opponent": r.opponent, "opponent_name": r.opponent_name,
                  "exp_cats": r.exp_cats, "p_win": r.p_win} for r in res.schedule.itertuples()] if len(res.schedule) else []
        playoff_games = []
        for w in sim.playoff_weeks:
            days = sim.weeks.days(w)
            counts = {tid: int(sim.model.team_week(tid, [Stint(p, slot=k) for k, p in enumerate(eng.league.rosters[tid])],
                                                    days, use_status=False).counted.sum()) for tid in eng.team_ids}
            playoff_games.append({"week": w, "start": days[0], "end": days[-1], "mine": counts[team],
                                  "avg": float(np.mean(list(counts.values())))})
        return clean({"n_sims": n, "strength_sd": sd, "start_week": res.start_week, "playoff_size": res.playoff_size,
                      "byes": byes, "playoff_weeks": sim.playoff_weeks, "reseed": sim.reseed,
                      "standings_known": sim.standings is not None, "notes": res.notes, "table": table,
                      "schedule": sched, "playoff_games": playoff_games})

    # ------------------------------------------------------------- sıralamalar
    @app.get("/api/leagues/{lid}/rankings")
    def rankings(lid: str, source: str = Query("ros", pattern="^(ros|season|preseason)$"), injuries: bool = True):
        eng = engine(lid, injuries)
        mode = {"ros": ROS, "season": "season_total", "preseason": "preseason"}[source]
        view = eng.before[mode]
        probs = eng.league_probabilities() if mode == ROS else None
        teams = []
        for tid in eng.team_ids:
            row = {"team_id": tid, "team": eng.league.teams[tid],
                   "totals": {c: view.totals.loc[tid, c] for c in CATEGORIES},
                   "ranks": {c: view.ranks.loc[tid, c] for c in CATEGORIES},
                   "avg_rank": float(view.ranks.loc[tid].mean()),
                   "coverage": {k: int(v) for k, v in view.coverage.loc[tid].items()}}
            if probs is not None:
                row["ecw"] = probs.loc[tid, "ECW"]
                row["p5"] = probs.loc[tid, "P_5_plus"]
                row["p"] = {c: probs.loc[tid, c] for c in CATEGORIES}
            teams.append(row)
        teams.sort(key=lambda r: r["avg_rank"])
        return clean({"source": source, "mode_label": MODES[mode], "teams": teams,
                      "labels": {c: CATEGORY_LABELS[c] for c in CATEGORIES}})

