"""Sezon içi uç noktalar: takas önerileri, yanlış fiyatlama, bu hafta + streaming, boştakiler, sezon, sıralamalar."""

from __future__ import annotations

import datetime as dt

import numpy as np
from fastapi import FastAPI, HTTPException, Query

from fdo.api.schemas import AddDropWeekIn, CompleteIn, DropIn, StrategyIn, StreamIn, SuggestIn, WaiverIn, WeeklyIn
from fdo.api.serialize import (assumed_strategies, brief, category_deltas, clean, games_delta, injury_info,
                               player_row, strategy_from, value_ranks)
from fdo.api.state import AppState
from fdo.evaluation.cases import summarize
from fdo.inseason.adddrop import available_from, critical_categories, critical_strategy, pick_critical
from fdo.inseason.drops import drop_plan, returning
from fdo.inseason.fixtures import opponent as fixture_opponent
from fdo.inseason.history import team_history
from fdo.inseason.sitstart import plan_week, today_changes
from fdo.inseason.waiver import drop_ranking, waiver_table
from fdo.inseason.weekly import DEFAULT_OUT, Stint, WeekOutlook, acquisition_limit, vector_totals
from fdo.roster.assignment import best_assignment
from fdo.trade import Strategy, TradeError
from fdo.trade.data import MODES, ROS
from fdo.trade.perception import mispricing, perceived_prices
from fdo.trade.strategy import CATEGORIES
from fdo.trade.suggest import CompleteOptions, SearchOptions, complete_trade, suggest_trades
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
                                 body.min_view if body.mode == "mutual" else 0.0, body.require_reason,
                                 body.max_view)
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
            pair = {body.team: strategy, r.team_b: s.other_strategy}
            rosters, adj, il = eng.resolve(r, pair)
            p, _ = eng.score(rosters, body.team, r.team_b, strategy, s.other_strategy, il)
            taken = float(perceived.reindex(list(r.give_b)).fillna(0).sum())
            active = [x for x in rosters[body.team] if x not in il[body.team]]
            rows.append({"my_categories": category_deltas(eng, p, body.team, pair),
                         "other_categories": category_deltas(eng, p, r.team_b, pair),
                         "playoff_games": games_delta(po_games, eng.league.rosters[body.team], rosters[body.team]),
                         "position_gap": best_assignment(eng.positions(active), eng.config).n_open_active,
                         "perceived_view": float(perceived.reindex(list(r.give_a)).fillna(0).sum()) / taken
                         if taken > 0 else None,"team_b": r.team_b, "team_b_name": eng.league.teams[r.team_b],
                         "give_a": [_brief(eng, p) for p in r.give_a], "give_b": [_brief(eng, p) for p in r.give_b],
                         "own_delta": s.own_strategy_delta, "other_delta": s.other_strategy_delta,
                         "own_win": s.own_win_delta, "other_win": s.other_win_delta, "fairness": s.fairness,
                         "perceived_balance": s.perceived_balance, "score": s.score, "mode": s.mode,
                         "acceptability": s.acceptability, "counterpart_reasons": list(s.counterpart_reasons),
                         "key_players": list(s.key_players), "other_strategy": s.other_strategy.name,
                         "other_weights": list(s.other_strategy.weights),
                         "adjustments": {t: {k: [eng.data.players.loc[p, "name"] for p in v] for k, v in a.items()}
                                         for t, a in adj.items()}})
        out = clean({"suggestions": rows, "strategy": {"name": strategy.name, "weights": list(strategy.weights)},
                     "examined": found.examined, "eligible": found.eligible,
                     "rejected_balance": found.rejected_fairness, "rejected_view": found.rejected_view,
                     "rejected_roster": found.rejected_roster, "rejected_reason": found.rejected_reason,
                     "rejected_overpay": found.rejected_overpay,
                     "limit_reached": found.limit_reached, "message": found.message})
        out["decision_id"] = state.log_decision("recommendation", "trade_suggest", lid, body.model_dump(),
                                                summarize(out))
        return out

    @app.post("/api/leagues/{lid}/trade/complete")
    def complete(lid: str, body: CompleteIn):
        """Takas ekranındaki seçimi tamamla ya da dengele (README §13.27)."""
        eng = engine(lid, body.injuries)
        team_check(eng, body.team_a)
        team_check(eng, body.team_b)
        sa, sb = _strategy(body.strategy_a, eng, body.team_a), _strategy(body.strategy_b, eng, body.team_b)
        try:
            opts = CompleteOptions(max_extra=body.max_extra, max_evaluations=body.max_evaluations,
                                   min_fairness=body.min_fairness, min_view=body.min_view, perceived=body.perceived,
                                   auto_balance=body.auto_balance, require_reason=body.require_reason,
                                   max_view=body.max_view)
            found = complete_trade(eng, body.team_a, body.team_b, tuple(body.give_a), tuple(body.give_b),
                                   strategy_a=sa, strategy_b=sb, options=opts)
        except (ValueError, TradeError) as e:
            raise HTTPException(400, str(e)) from e
        fixed = set(body.give_a) | set(body.give_b)
        pair = {body.team_a: sa, body.team_b: sb}

        def row(s):
            r = s.request
            rosters, adj, il = eng.resolve(r, pair)
            p, _ = eng.score(rosters, r.team_a, r.team_b, sa, sb, il)
            return {"give_a": [{**_brief(eng, x), "added": x not in fixed} for x in r.give_a],
                    "give_b": [{**_brief(eng, x), "added": x not in fixed} for x in r.give_b],
                    "tier": s.mode, "score": s.score, "own_delta": s.own_strategy_delta,
                    "other_delta": s.other_strategy_delta, "own_win": s.own_win_delta, "other_win": s.other_win_delta,
                    "fairness": s.fairness, "perceived_view": s.perceived_balance,
                    "acceptability": s.acceptability, "counterpart_reasons": list(s.counterpart_reasons),
                    "my_categories": category_deltas(eng, p, r.team_a, pair),
                    "adjustments": {t: {k: [eng.data.players.loc[x, "name"] for x in v] for k, v in a.items()}
                                    for t, a in adj.items()}}
        out = clean({"kind": found.kind, "suggestions": [row(s) for s in found.suggestions],
                     "current": row(found.current) if found.current else None, "examined": found.examined,
                     "rejected_balance": found.rejected_fairness, "rejected_view": found.rejected_view,
                     "rejected_roster": found.rejected_roster, "rejected_reason": found.rejected_reason,
                     "rejected_overpay": found.rejected_overpay, "max_view": opts.max_view,
                     "limit_reached": found.limit_reached,
                     "min_fairness": opts.min_fairness, "min_view": opts.min_view, "message": found.message})
        out["decision_id"] = state.log_decision("recommendation", "trade_complete", lid, body.model_dump(),
                                                summarize(out))
        return out

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

    def _acc(lid: str, body: WeeklyIn, wk: int, current: int, opp: str):
        """Haftanın şu ana kadarki skoru: elle girilen, yoksa (bu hafta için) Yahoo senkronizasyonu."""
        lv = state.live(lid, body.injuries) if wk == current else None
        mine = body.acc_mine if body.acc_mine is not None else (lv.totals.get(body.team) if lv else None)
        theirs = body.acc_opp if body.acc_opp is not None else (lv.totals.get(opp) if lv else None)
        return mine, theirs, lv

    def _default_droppable(eng, model, body) -> list[str]:
        """Kalan sezonda en kolay bırakılabilecek 3 aktif oyuncu (boştakilerle değişim sırası, sonra piyasa değeri)."""
        drops = drop_ranking(eng, body.team, _strategy(body.strategy, eng, body.team))
        active = model.active_roster(body.team)
        ranked = [p for p in (list(drops["drop"]) if len(drops) else []) if p in active]
        cheapest = sorted(active, key=lambda p: float(eng.market.get(p, 0.0)))     # kalan sezon değeri en düşük
        return list(dict.fromkeys([*ranked, *cheapest]))[:3]

    def _availability(lid: str, eng, injuries: bool) -> dict:
        """Waiver'daki oyuncu → ilk alınabilir gün (senkronizasyon yoksa boş: herkes FA sayılır)."""
        lv = state.live(lid, injuries)
        return available_from(lv.waivers, eng.data.as_of, eng.league.settings) if lv else {}

    def _weeks_list(weeks, current):
        return [{"week": int(w), "start": r.start, "end": r.end, "playoff": bool(r.playoff), "current": int(w) == current}
                for w, r in weeks.weeks.iterrows() if int(w) >= current]

    @app.post("/api/leagues/{lid}/weekly")
    def weekly(lid: str, body: WeeklyIn):
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        acc_mine, acc_opp, lv = _acc(lid, body, wk, current, opp)
        o = model.outlook(body.team, opp, days, acc_mine=acc_mine, acc_opp=acc_opp, week=wk)
        active = model.active_roster(body.team)
        default_drop = _default_droppable(eng, model, body)
        return clean({"weeks": _weeks_list(weeks, current), "current_week": current, "week": wk,
                      "week_start": weeks.weeks.loc[wk, "start"], "days": days, "opponent": opp,
                      "opponent_name": eng.league.teams[opp], "fixture_opponent": fx_opp,
                      "started": wk == current and eng.data.as_of > weeks.weeks.loc[wk, "start"],
                      "acquisitions_limit": acquisition_limit(eng.league.settings),
                      "live": {"captured_at": lv.captured_at, "partial_today": lv.live, "mine": lv.totals.get(body.team),
                               "opp": lv.totals.get(opp), "category_wins": [lv.category_wins.get(body.team),
                                                                            lv.category_wins.get(opp)],
                               "adds_used": lv.adds_used if body.team == lv.my_team else None,
                               "manual": body.acc_mine is not None or body.acc_opp is not None} if lv else None,
                      "active_roster": [_brief(eng, p) for p in active], "default_droppable": default_drop,
                      "outlook": _outlook(eng, o), "notes": list(weeks.notes)})

    @app.post("/api/leagues/{lid}/weekly/stream")
    def stream(lid: str, body: StreamIn):
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        acc_mine, acc_opp, lv = _acc(lid, body, wk, current, opp)
        base = model.outlook(body.team, opp, days, acc_mine=acc_mine, acc_opp=acc_opp, week=wk)
        used = body.used if body.used is not None else (lv.adds_used if lv and body.team == lv.my_team else 0) or 0
        left = max(0, acquisition_limit(eng.league.settings) - int(used))
        s = model.stream(base, moves=left, droppable=list(body.droppable), acc_mine=acc_mine,
                         available_from=_availability(lid, eng, body.injuries))
        moves = [{"day": m.day, "add": _brief(eng, m.add), "drop": _brief(eng, m.drop), "ros_delta": m.ros_delta,
                  "games": sum(model.has_game(m.add, d) for d in s.days if d >= m.day)} for m in s.moves]
        return clean({"moves": moves, "left": left, "before": {"p": list(base.p), "expected_wins": base.expected_wins,
                                                                "p5": base.p5},
                      "after": _outlook(eng, s)})

    @app.post("/api/leagues/{lid}/sitstart")
    def sitstart(lid: str, body: WeeklyIn):
        """Eşleşmeye göre günlük kadro önerisi (README §13.21)."""
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        acc_mine, acc_opp, lv = _acc(lid, body, wk, current, opp)
        plan = plan_week(model, body.team, opp, days, acc_mine=acc_mine, acc_opp=acc_opp)
        tw = plan.week
        players = []
        for j, pid in enumerate(plan.players):
            cells = []
            for d in range(len(days)):
                k = tw.slots[d, j]
                state_ = ("start" if k >= 0 else "sit" if plan.sat[d, j] else "bench" if tw.playing[d, j]
                          else "out" if tw.grid.iat[j, d] == "✕" else "")
                cells.append({"state": state_, "slot": plan.slot_names[k] if k >= 0 else None})
            players.append({**_brief(eng, pid), "value": plan.value[j],
                            "dp": {c: plan.dp[j, i] for i, c in enumerate(CATEGORIES)},
                            "games": int(tw.playing[:, j].sum()), "started": int((tw.slots[:, j] >= 0).sum()),
                            "yahoo_slot": eng.league.lineups.get(body.team, {}).get(pid), "cells": cells})
        score = lambda x: {"p": list(x.p), "expected_wins": x.expected_wins, "p5": x.p5, "strategy_score": x.strategy_score}
        as_of = eng.data.as_of
        today = None
        if wk == current and as_of in days and eng.league.lineups.get(body.team):
            ch = today_changes(plan, eng.league.lineups[body.team], as_of)
            today = {"day": as_of, **{k: [{**_brief(eng, r["player_id"]), **r} for r in v] for k, v in ch.items()}}
        return clean({"week": wk, "current_week": current, "weeks": _weeks_list(weeks, current), "days": days,
                      "opponent": opp, "opponent_name": eng.league.teams[opp], "fixture_opponent": fx_opp,
                      "slot_names": plan.slot_names, "before": score(plan.before), "after": score(plan.after),
                      "players": players, "today": today, "rounds": plan.rounds,
                      "live": {"captured_at": lv.captured_at, "partial_today": lv.live} if lv else None})

    @app.post("/api/leagues/{lid}/adddrop/week")
    def adddrop_week(lid: str, body: AddDropWeekIn):
        """Bu haftanın add/drop menüsü: tek hamleler ve kalan alım hakkıyla günlük plan (README §13.22)."""
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        acc_mine, acc_opp, lv = _acc(lid, body, wk, current, opp)
        avail = _availability(lid, eng, body.injuries)
        base = model.outlook(body.team, opp, days, acc_mine=acc_mine, acc_opp=acc_opp, week=wk)
        leverage = critical_categories(model, base, avail)
        bad = [c for c in body.categories or [] if c not in CATEGORIES]
        if bad:
            raise HTTPException(400, f"Bilinmeyen kategori: {bad}")
        chosen = body.categories or pick_critical(leverage)
        if body.mode == "critical":
            out = DEFAULT_OUT if body.sit_out else tuple(s for s in DEFAULT_OUT if s != "O")
            model = state.week_model(lid, body.injuries, critical_strategy(chosen), out)
            base = model.outlook(body.team, opp, days, acc_mine=acc_mine, acc_opp=acc_opp, week=wk)
        droppable = list(body.droppable) if body.droppable is not None else _default_droppable(eng, model, body)
        limit = acquisition_limit(eng.league.settings)
        used = body.used if body.used is not None else (lv.adds_used if lv and body.team == lv.my_team else 0) or 0
        left = max(0, limit - int(used))

        def avail_info(pid):
            return {"kind": "W", "from": avail[pid]} if pid in avail else {"kind": "FA", "from": None}

        singles = model.single_moves(base, droppable=droppable, acc_mine=acc_mine, available_from=avail)
        rows = [{"add": {**_brief(eng, r.add), "availability": avail_info(r.add)}, "drop": _brief(eng, r.drop),
                 "day": r.day, "games": r.games, "gain": r.gain, "d_expected_wins": r.d_expected_wins, "d_p5": r.d_p5,
                 "dp": {c: r.dp[i] for i, c in enumerate(CATEGORIES)}, "ros_delta": r.ros_delta}
                for r in singles.itertuples()] if len(singles) else []
        plan = None
        if body.plan and left > 0 and droppable:
            st = model.stream(base, moves=left, droppable=droppable, acc_mine=acc_mine, available_from=avail)
            plan = {"moves": [{"day": m.day, "add": {**_brief(eng, m.add), "availability": avail_info(m.add)},
                               "drop": _brief(eng, m.drop), "ros_delta": m.ros_delta,
                               "games": sum(model.has_game(m.add, d) for d in st.days if d >= m.day)} for m in st.moves],
                    "after": {"p": list(st.p), "expected_wins": st.expected_wins, "p5": st.p5}}
        mine = lv is not None and body.team == lv.my_team
        return clean({"week": wk, "current_week": current, "weeks": _weeks_list(weeks, current), "days": days,
                      "opponent": opp, "opponent_name": eng.league.teams[opp], "fixture_opponent": fx_opp,
                      "mode": body.mode, "objective": model.strategy.name, "chosen": chosen,
                      "categories": [{"key": c, "label": CATEGORY_LABELS[c], "p": base.p[i], "leverage": leverage[i],
                                      "chosen": c in chosen} for i, c in enumerate(CATEGORIES)],
                      "base": {"p": list(base.p), "expected_wins": base.expected_wins, "p5": base.p5},
                      "adds_limit": limit, "adds_used": used, "adds_left": left, "fab": lv.fab if mine else None,
                      "waiver_time": eng.league.settings.get("Waiver Time"),
                      "waiver_type": eng.league.settings.get("Waiver Type"), "synced": lv is not None,
                      "singles": rows, "plan": plan, "droppable": droppable,
                      "active_roster": [_brief(eng, p) for p in model.active_roster(body.team)]})

    @app.post("/api/leagues/{lid}/adddrop/drops")
    def adddrop_drops(lid: str, body: DropIn):
        """Yalnız bırakma: IL'den dönen oyuncuya yer açarken kimi bırakmalı (README §13.26)."""
        eng, weeks, current, wk, days, fx_opp, opp, model = _week_setup(lid, body)
        acc_mine, acc_opp, lv = _acc(lid, body, wk, current, opp)
        lg = eng.league
        il = [p for p in lg.rosters[body.team] if p in lg.injury_rosters[body.team]]
        ready = returning(model, body.team, eng.data.as_of)
        bad = [p for p in body.activate or [] if p not in il]
        if bad:
            raise HTTPException(400, f"IL'de olmayan oyuncu: {bad}")
        plan = drop_plan(model, body.team, opp, days, ready if body.activate is None else list(body.activate),
                         acc_mine=acc_mine, acc_opp=acc_opp)
        swaps = drop_ranking(eng, body.team, model.strategy)            # boşta daha iyisi varsa bırakmak bedava
        better = {r.drop: (r.add, r.score) for r in swaps.itertuples() if r.score > 0} if len(swaps) else {}
        ranks = value_ranks(eng)
        nxt = weeks.days(wk + 1) if wk + 1 in weeks.weeks.index else []

        def ret(p):
            d = model.return_date.get(p)
            return None if d is None or d == dt.date.max else d

        rows = []
        for r in plan.rows.itertuples():
            p = r.player
            alt = better.get(p)
            rows.append({"player": {**_brief(eng, p), "injury": injury_info(eng, p), "return_date": ret(p),
                                    "rank": float(ranks[p]) if p in ranks.index else None},
                         "returning": r.returning, "ros_loss": r.ros_loss, "ros_d_ecw": r.ros_d_ecw, "ros_dp": r.ros_dp,
                         "week_loss": r.week_loss, "week_d_expected": r.week_d_expected, "week_d_p5": r.week_d_p5,
                         "week_dp": r.week_dp, "games": r.games, "games_left": r.games_left,
                         "games_next": model.games_in(p, nxt), "open_slots": r.open_slots,
                         "replacement": {"add": _brief(eng, alt[0]), "score": alt[1]} if alt else None})
        p0, ew0, p50 = plan.week_base
        return clean({"week": wk, "current_week": current, "weeks": _weeks_list(weeks, current), "days": days,
                      "opponent": opp, "opponent_name": eng.league.teams[opp], "fixture_opponent": fx_opp,
                      "objective": model.strategy.name, "capacity": lg.capacity,
                      "active_count": len(model.active_roster(body.team)),
                      "il": [{**_brief(eng, p), "injury": injury_info(eng, p), "return_date": ret(p),
                              "season": model.return_date.get(p) == dt.date.max, "ready": p in ready,
                              "activated": p in plan.activate} for p in il],
                      "activate": plan.activate, "need": plan.need, "recommended": plan.recommended,
                      "base": {"p": list(p0), "expected_wins": ew0, "p5": p50}, "rows": rows,
                      "synced": lv is not None})

    @app.get("/api/leagues/{lid}/history")
    def history(lid: str, team: str, injuries: bool = True):
        """Geçmiş haftaların kategori değerleri ve ligdeki sıra (README §13.23)."""
        eng = engine(lid, injuries)
        team_check(eng, team)
        weeks = state.weeks(lid, injuries)
        h = team_history(state.data_dir, lid, team, state.live(lid, injuries))
        for r in h["weeks"]:
            w = r["week"]
            r["start"], r["end"] = (weeks.weeks.loc[w, "start"], weeks.weeks.loc[w, "end"]) if w in weeks.weeks.index \
                else (None, None)
            if r["result"] and r["result"]["opponent"] in eng.league.teams:
                r["result"]["opponent_name"] = eng.league.teams[r["result"]["opponent"]]
        return clean({**h, "team": eng.league.teams[team], "synced": state.live(lid, injuries) is not None})

    # ------------------------------------------------------------- boştakiler
    @app.post("/api/leagues/{lid}/waiver")
    def waiver(lid: str, body: WaiverIn):
        team, injuries = body.team, body.injuries
        eng = engine(lid, injuries)
        team_check(eng, team)
        strategy = _strategy(body.strategy, eng, team)
        t = waiver_table(eng, team, strategy, top=body.top)
        avail = _availability(lid, eng, injuries)
        weeks = state.weeks(lid, injuries)
        wk = weeks.week_of(eng.data.as_of)
        model = state.week_model(lid, injuries)
        this_days = weeks.days(wk, eng.data.as_of) if wk else []
        next_days = weeks.days(wk + 1) if wk and wk + 1 in weeks.weeks.index else []
        z = state.per_game_z(lid, "ros", injuries)
        ranks = value_ranks(eng)
        rows = []
        for r in t.itertuples():
            row = player_row(eng, r.add, "ros", z, ranks=ranks)
            row["availability"] = {"kind": "W", "from": avail[r.add]} if r.add in avail else {"kind": "FA", "from": None}
            rows.append({"add": row, "drop": _brief(eng, r.drop),
                         "score": r.score, "delta_ecw": r.delta_ecw,
                         "dp": {c: getattr(r, f"d_{c}") for c in CATEGORIES},
                         "games_this_week": sum(model.has_game(r.add, d) for d in this_days),
                         "games_next_week": sum(model.has_game(r.add, d) for d in next_days)})
        d = drop_ranking(eng, team, strategy)
        drops = [{"drop": _brief(eng, x.drop), "best_add": _brief(eng, x.add), "score": x.score}
                 for x in d.itertuples()] if len(d) else []
        lv = state.live(lid, injuries)
        mine = lv is not None and team == lv.my_team
        return clean({"rows": rows, "drops": drops, "days_this_week": len(this_days), "week": wk,
                      "adds_left": lv.adds_left(team, acquisition_limit(eng.league.settings)) if mine else None,
                      "fab": lv.fab if mine else None, "synced": lv is not None,
                      "waiver_time": eng.league.settings.get("Waiver Time"),
                      "waiver_type": eng.league.settings.get("Waiver Type")})

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

