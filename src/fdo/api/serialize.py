"""API yanıtları için JSON'a uygun dönüşümler (NaN → null, numpy → Python)."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from fdo.api.state import SOURCES
from fdo.trade.data import MODES
from fdo.trade.engine import TradeEngine, TradeResult
from fdo.trade.report import category_changes
from fdo.trade.strategy import CATEGORIES, PRESETS, Strategy
from fdo.types import CATEGORY_LABELS

PER_GAME = ("fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov")
CAT_STAT = {"FG3M": "fg3m", "PTS": "pts", "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "tov"}


def clean(obj):
    """JSON'a uygun: NaN/inf → None, numpy sayıları → Python, tarih → ISO."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [clean(x) for x in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, (dt.date, pd.Timestamp)):
        return obj.isoformat() if not pd.isna(obj) else None
    if obj is pd.NaT:
        return None
    return obj


def categories_meta() -> list[dict]:
    return [{"key": c, "label": CATEGORY_LABELS[c], "lower_is_better": c == "TOV"} for c in CATEGORIES]


def strategy_from(payload: dict | None, eng: TradeEngine | None = None, team: str | None = None) -> Strategy:
    """``{"preset": ..}``, ``{"name": .., "weights": [9]}`` ya da ``{"auto_punt": 1|2}`` (takımın kategori
    profilinden en zayıf kategori(ler)i punt; ``eng`` ve ``team`` gerekir); yoksa dengeli."""
    if not payload:
        return Strategy()
    if payload.get("auto_punt") or payload.get("auto_revive"):
        if eng is None or team is None:
            raise ValueError("Otomatik strateji için takım gerekli")
        probs = eng.league_probabilities().loc[team, list(CATEGORIES)].to_numpy()
        if payload.get("auto_punt"):
            auto = Strategy.adaptive(probs, int(payload["auto_punt"]))
            punted = [CATEGORY_LABELS[c] for c, w in zip(CATEGORIES, auto.weights) if w == 0]
            return Strategy(f"Otomatik: punt {' + '.join(punted)}", auto.weights)
        auto = Strategy.revive(probs, int(payload["auto_revive"]))
        weak = [CATEGORY_LABELS[c] for c, w in zip(CATEGORIES, auto.weights) if w > 1]
        return Strategy(f"Canlandır: {' + '.join(weak)} ×3", auto.weights)
    if payload.get("preset"):
        return Strategy.preset(payload["preset"])
    w = payload.get("weights")
    if w:
        return Strategy(str(payload.get("name") or "Özel"), tuple(float(x) for x in w))
    return Strategy()


def assumed_strategies(eng: TradeEngine, assumption: str, teams) -> dict[str, Strategy]:
    """Rakip strateji varsayımı: ``balanced`` (boş sözlük = dengeli) ya da ``punt1``/``punt2`` (profilden)."""
    if assumption not in ("punt1", "punt2"):
        return {}
    probs = eng.league_probabilities()
    k = 1 if assumption == "punt1" else 2
    return {t: Strategy.adaptive(probs.loc[t, list(CATEGORIES)].to_numpy(), k) for t in teams}


def brief(eng: TradeEngine, pid: str) -> dict:
    P = eng.data.players
    return {"id": pid, "name": P.loc[pid, "name"], "nba_team": P.loc[pid, "nba_team"],
            "positions": [p for p in str(P.loc[pid, "yahoo_positions"]).split(",") if p],
            "status": P.loc[pid, "injury_status"] or ""}


def category_deltas(eng: TradeEngine, p_after: np.ndarray, team_id: str,
                    strategies: dict[str, Strategy]) -> dict[str, float]:
    """Takımın rakiplere karşı ortalama kategori kazanma olasılığı değişimi (takas sonrası − önce);
    ``strategies``: takastaki bütün takımlar (``TradeEngine.before_matrix`` ile aynı taban)."""
    d = eng.category_profile(p_after, team_id) - eng.category_profile(eng.before_matrix(strategies), team_id)
    return {c: float(x) for c, x in zip(CATEGORIES, d)}


def games_delta(games: dict[str, int], before, after) -> int | None:
    """Kadronun playoff haftalarındaki toplam NBA maçı farkı (otomatik bırak/ekle dahil); bilinmiyorsa None."""
    if not games:
        return None
    return sum(games.get(p, 0) for p in after) - sum(games.get(p, 0) for p in before)


def fixture_changes(sim, teams, rosters: dict, injuries: dict) -> list[dict]:
    """Takastaki her takım için kalan normal sezon haftaları: rakip ve haftayı kazanma olasılığı önce/sonra
    (``SeasonSim.fixture_outlook``, nokta tahmini). ``partner``: rakip de takasta (onun kadrosu da değişti)."""
    out = []
    for t in teams:
        before, after = sim.fixture_outlook(t), sim.fixture_outlook(t, rosters, injuries)
        weeks = [{"week": int(b.week), "start": b.start, "opponent": b.opponent, "opponent_name": b.opponent_name,
                  "p_before": b.p_win, "p_after": a.p_win, "exp_before": b.exp_cats, "exp_after": a.exp_cats,
                  "partner": b.opponent in teams}
                 for b, a in zip(before.itertuples(), after.itertuples())]
        out.append({"team_id": t, "team": sim.league.teams[t], "weeks": weeks,
                    "wins_before": float(before["p_win"].sum()), "wins_after": float(after["p_win"].sum())})
    return out


def plain_metrics(plain, request, strategies: dict, keys=("ecw_delta", "win_delta", "strategy_delta")) -> dict | None:
    """Aynı takasın bedava waiver hamleleri varsayılmadan (``free_moves=False`` motoru) takım başına farkları; takas bu
    varsayımla çözülemezse ``None``."""
    try:
        rosters, _, il = plain.resolve(request, strategies)
        _, m = plain.score_many(rosters, strategies, il)
    except Exception:  # noqa: BLE001 — yalnız açıklama; ana sonuç etkilenmez
        return None
    return {t: {k: m[t][k] for k in keys} for t in strategies}


def season_effect(sim, base, after, team: str) -> dict:
    """``SeasonSim.effect`` → JSON: ölçü başına önce, sonra, eşleşmeli fark, standart hata, gürültüden ayrılıyor mu."""
    return {k: {"before": d.before, "after": d.after, "delta": d.delta, "se": d.se, "clear": d.clear}
            for k, d in sim.effect(base, after, team).items()}


def presets() -> list[dict]:
    return [{"name": n, "weights": list(Strategy.preset(n).weights)} for n in PRESETS]


def injury_info(eng: TradeEngine, pid: str) -> dict | None:
    inj = getattr(eng.data, "injuries", None)
    if inj is None or pid not in inj.index:
        return None
    r = inj.loc[pid]
    return {"kind": r["kind"], "return_date": r["return_date"], "text": r.get("status_text", ""),
            "injury": r.get("injury", "")}


def durability_info(eng: TradeEngine, pid: str) -> dict | None:
    """Kalan sezon maçı oynama oranıyla kısıldıysa: oran ve Yahoo'nun ham kalan sezon maçı."""
    dur = getattr(eng.data, "durability", None)
    if dur is None or pid not in dur.index or dur.loc[pid, "ros_gp_after"] >= dur.loc[pid, "ros_gp_before"] - 1e-9:
        return None
    r = dur.loc[pid]
    return {"rate": float(r["rate"]), "yahoo_gp": float(r["ros_gp_before"]), "games_left": int(r["games_left"])}


def player_row(eng: TradeEngine, pid: str, source: str, z: pd.DataFrame, *, il: frozenset = frozenset(),
               ranks: pd.Series | None = None, perceived: pd.DataFrame | None = None) -> dict:
    """``perceived``: ``AppState.perceived`` (bu sezon / sezon öncesi kaynağında algılanan değer ve sıra)."""
    P = eng.data.players
    f = eng.data.stats[SOURCES[source]]
    row = f.loc[pid] if pid in f.index else None
    gp = float(row["gp"]) if row is not None and pd.notna(row["gp"]) else None
    per = {}
    if row is not None and gp and gp > 0:
        per = {s: float(row[s]) / gp if pd.notna(row[s]) else None for s in PER_GAME}
    stats = {c: per.get(CAT_STAT[c]) for c in CAT_STAT}
    for c, (m, a) in {"FG_PCT": ("fgm", "fga"), "FT_PCT": ("ftm", "fta")}.items():
        stats[c] = per[m] / per[a] if per.get(m) is not None and per.get(a) else None
    zrow = z.loc[pid] if pid in z.index else None
    pc = perceived.loc[pid] if perceived is not None and pid in perceived.index else None
    return clean({
        "id": pid, "name": P.loc[pid, "name"], "nba_team": P.loc[pid, "nba_team"],
        "positions": [p for p in str(P.loc[pid, "yahoo_positions"]).split(",") if p],
        "status": P.loc[pid, "injury_status"] or "", "il": pid in il,
        "injury": injury_info(eng, pid), "modeled": bool(eng.modeled[eng.index[pid]]),
        "gp": gp, "durability": durability_info(eng, pid) if source == "ros" else None,
        "stats": stats, "attempts": {k: per.get(k) for k in ("fgm", "fga", "ftm", "fta")},
        "z": {c: (float(zrow[c]) if zrow is not None and c in zrow else None) for c in CATEGORIES},
        "value": float(eng.market.get(pid, 0.0)),
        "rank": float(ranks[pid]) if ranks is not None and pid in ranks.index else None,
        "perceived_value": float(pc["price"]) if pc is not None else None,
        "perceived_rank": float(pc["rank"]) if pc is not None else None,
        "perceived_fallback": bool(pc["fallback"]) if pc is not None else None,
    })


def value_ranks(eng: TradeEngine) -> pd.Series:
    modeled = [p for p in eng.ids if eng.modeled[eng.index[p]]]
    return eng.market.loc[modeled].rank(ascending=False, method="first")


def return_timeline(eng: TradeEngine, roster, il, strategy, incoming=()) -> list[dict]:
    """IL dönüş takvimi (``TradeEngine.crunch_plan``): kim döner, kim bırakılır. ``self_cut``: dönen oyuncu kadroya
    girecek kadar değerli değil (kimseyi yerinden etmez); ``incoming``: bırakılan, takasla gelen oyuncu."""
    names = eng.data.players["name"]
    gelen = set(incoming)
    out = []
    for r, d in eng.crunch_plan(roster, il, strategy):
        out.append({"returning": {"id": r, "name": names[r]}, "date": eng.return_day(r),
                    "dropped": {"id": d, "name": names[d]} if d else None, "self_cut": d == r,
                    "incoming": bool(d) and d in gelen})
    return out


def trade_result(eng: TradeEngine, result: TradeResult, *, perceived: pd.Series | None = None) -> dict:
    a, b = result.request.team_a, result.request.team_b
    names = eng.data.players["name"]
    # Takassız alternatif: takas öncesi tabanın bedava waiver hamleleri (ortak havuz) ve tek başına kazancı.
    free = eng.joint_waiver([(t, eng.league.rosters[t], eng._il(t, eng.league.rosters[t]), result.strategies[t])
                             for t in (a, b)])
    teams = {}
    for side, tid in (("a", a), ("b", b)):
        i = eng.team_index[tid]
        keep = np.arange(len(eng.team_ids)) != i
        pb = result.probabilities_before[i, keep].mean(axis=0)
        pa = result.probabilities_after[i, keep].mean(axis=0)
        m = result.metrics.loc[tid]
        adj = result.adjustments[tid]
        teams[side] = {
            "team_id": tid, "team": eng.league.teams[tid], "strategy": result.strategies[tid].name,
            "ecw_before": m.ecw_before, "ecw_after": m.ecw_after, "ecw_delta": m.ecw_delta,
            "win_before": m.win_before, "win_after": m.win_after, "win_delta": m.win_delta,
            "strategy_before": m.strategy_before, "strategy_after": m.strategy_after,
            "strategy_delta": m.strategy_delta, "fit_score": result.assessments["fit_scores"][tid],
            "categories": [{"key": c, "label": CATEGORY_LABELS[c], "before": float(x), "after": float(y)}
                           for c, x, y in zip(CATEGORIES, pb, pa)],
            "adjustments": {k: [{"id": p, "name": names[p]} for p in v] for k, v in adj.items()},
            "ranks": {mode: [{"key": c, "label": CATEGORY_LABELS[c], "value_before": r["önce"], "value_after": r["sonra"],
                              "rank_before": r["sıra önce"], "rank_after": r["sıra sonra"]}
                             for c, r in category_changes(result, mode, tid).iterrows()] for mode in MODES},
        }
        base = float(eng.baseline_p[i, keep].mean(axis=0).sum())
        teams[side]["free"] = {"moves": [{"drop": names[d] if d else None, "add": names[f]} for d, f in free[tid][1]],
                               "ecw_gain": float(pb.sum()) - base}
    req = result.request
    balance = None
    if perceived is not None:
        given = float(perceived.reindex(list(req.give_a)).fillna(0).sum())
        taken = float(perceived.reindex(list(req.give_b)).fillna(0).sum())
        balance = given / taken if taken > 0 else None
    for side, tid in (("a", a), ("b", b)):
        teams[side]["net_value"] = result.assessments["roster_values"][tid]
    return clean({"teams": teams, "fairness": result.assessments["fairness_ratio"],
                  "roster_balance": result.assessments["roster_balance"], "perceived_balance": balance,
                  "assessments": {k: v for k, v in result.assessments.items() if k not in ("fit_scores", "roster_values")},
                  "notes": result.notes, "modes": MODES})
