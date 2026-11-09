"""Takas için yazılı detaylı analiz (Claude; README §13.29).

Model hesapları (dört istatistik temeli, IL dönüş takvimi, karşı teklif adayları) ile oyuncuların bu sezonu, Yahoo
projeksiyonu, son maç formu, NBA takımındaki rol (son 5 maçta dakika ve şut payı, sakat takım arkadaşları ve dönüş
tarihleri) ve haberler tek bir veri paketinde toplanır; Claude bunlardan Türkçe, yapılandırılmış bir değerlendirme
yazar (karar, bölümler, karşı teklifler, izlenecekler). Yalnız paketteki veriler kullanılır; genel basketbol bilgisi
(yaş, kariyer normları) veriyle çelişmediği sürece ve belirtilerek.

Raporlar ``trade_reports.json``'da saklanır (veri imzası + takas + stratejiler anahtarıyla): aynı veriyle aynı takas
yeniden ücret ödemeden açılır. Üretim arka planda çalışır (Cloudflare 100 sn sınırı); arayüz durumu sorar.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.inseason.news import PRICES, load_env_key, model_name
from fdo.inseason.roles import match_ids
from fdo.trade.data import ROS
from fdo.trade.engine import TradeEngine
from fdo.trade.perception import perceived_ranks
from fdo.trade.strategy import CATEGORIES
from fdo.types import CATEGORY_LABELS

FILE = "trade_reports.json"
KEEP = 60
EFFORT = "medium"

SYSTEM = """You are an expert fantasy basketball analyst for Yahoo head-to-head 9-category leagues (FG%, FT%, 3PM, PTS, \
REB, AST, STL, BLK, TO; fewer turnovers is better). The user receives a trade offer or is considering one. You get one \
JSON data packet with everything the app knows. Write the evaluation in Turkish, in the requested JSON format.

How to evaluate:
- Judge both what players have actually done this season and what is projected for the rest of the season. The app's \
model scores the trade on four stat bases (Yahoo projection, this season's rates, last 10 games, a blend weighted by games \
played). If the bases agree, say the conclusion is robust. If they disagree, explain which rates are more believable for \
each player and why, using minutes, shot volume, usage, recent games, teammates returning from injury, role news, \
sample size and durability, and give your own most plausible view.
- Roles matter: a player's production depends on his minutes and shots on his NBA team. Check the team context: \
injured teammates who will return (with dates) can take shots and the ball away; a returning starter can push a player \
to the bench.
- Roster spots: in a 2-for-1 or 3-for-2 the user must drop players. Use the roster list and the IL return timeline \
(who returns when and who would be cut). A returning player who is not better than the weakest active player does not \
displace anyone. If an incoming player would be cut at an IL return, his value only lasts until then. Weigh the value \
of a roster spot using the league settings (waivers, weekly adds).
- Explain why the other manager may want this deal (perceived/name value vs 9-category value).
- Counter offers: propose at most 3, using only players on the two rosters, preferably from the counter-offer \
candidates the app computed (they come with model numbers). Use the exact player ids from the packet.
- Be honest about uncertainty. The model's probabilities are not calibrated. Use only facts in the packet; general \
basketball knowledge (age, career norms) is allowed only when it does not contradict the packet, and say when you use it. \
Never invent injuries, trades, news or numbers.

Style: concise, concrete, numbers with context (e.g. "25,9 sayı, %41,3 isabet (23 şut)"). Turkish decimal commas. \
No filler, no repetition between sections."""

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["kabul et", "karşı teklif ver", "reddet", "bekle"]},
        "confidence": {"type": "string", "enum": ["düşük", "orta", "yüksek"]},
        "headline": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "points"], "additionalProperties": False}},
        "counter_offers": {"type": "array", "items": {
            "type": "object",
            "properties": {"give_ids": {"type": "array", "items": {"type": "string"}},
                           "get_ids": {"type": "array", "items": {"type": "string"}},
                           "why": {"type": "string"}},
            "required": ["give_ids", "get_ids", "why"], "additionalProperties": False}},
        "watch": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "confidence", "headline", "sections", "counter_offers", "watch"],
    "additionalProperties": False,
}

CATS = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "fg3m", "STL": "stl", "BLK": "blk", "TOV": "tov"}


def _r(x, k=1):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), k)


def per_game(frame: pd.DataFrame, pid: str) -> dict | None:
    if pid not in frame.index:
        return None
    row = frame.loc[pid]
    gp = row.get("gp")
    if gp is None or pd.isna(gp) or gp <= 0:
        return None
    out = {c: _r(row[s] / gp) for c, s in CATS.items()}
    out["FG_PCT"] = _r(row["fgm"] / row["fga"], 3) if row["fga"] else None
    out["FT_PCT"] = _r(row["ftm"] / row["fta"], 3) if row["fta"] else None
    out["FGA"] = _r(row["fga"] / gp)
    return {"games": _r(gp, 1), **out}


def _logs_for(logs: pd.DataFrame | None, ids: pd.Series | None, pid: str) -> pd.DataFrame:
    if logs is None or ids is None:
        return pd.DataFrame()
    return logs[ids == pid].sort_values("game_date")


def form(games: pd.DataFrame) -> dict | None:
    """Son 5 maç ortalaması ve son 10 maç tek tek."""
    if games.empty:
        return None
    last5 = games.tail(5)
    avg = {c: _r(last5[s].mean()) for c, s in CATS.items()}
    avg["MIN"] = _r(last5["minutes"].mean())
    avg["FG_PCT"] = _r(last5["fgm"].sum() / last5["fga"].sum(), 3) if last5["fga"].sum() else None
    avg["FGA"] = _r(last5["fga"].mean())
    rows = [[str(r.game_date)[5:10], int(round(r.minutes)), int(r.pts), f"{int(r.fgm)}/{int(r.fga)}", int(r.reb),
             int(r.ast), int(r.tov)] for r in games.tail(10).itertuples()]
    return {"season_minutes": _r(games["minutes"].mean()), "last5": avg,
            "last10_games[date,min,pts,fg,reb,ast,tov]": rows}


def team_context(eng: TradeEngine, logs: pd.DataFrame | None, ids: pd.Series | None, team: str, me: str) -> dict:
    """NBA takımında son 5 maçın rotasyonu ve sakat takım arkadaşları (dönüş tarihi, bu sezon oynadığı maç)."""
    names = eng.data.players["name"]
    out: dict = {"team": team}
    if logs is not None and len(logs):
        t = logs[logs["nba_team"] == team]
        dates = sorted(t["game_date"].unique())[-5:]
        recent = t[t["game_date"].isin(dates)]
        rot = recent.groupby("name").agg(min=("minutes", "mean"), fga=("fga", "mean"), pts=("pts", "mean"),
                                         games=("game_date", "nunique")).sort_values("min", ascending=False).head(9)
        out["rotation_last5_games"] = [{"name": n, "min": _r(r["min"]), "fga": _r(r["fga"]), "pts": _r(r["pts"]),
                                        "games": int(r["games"])} for n, r in rot.iterrows()]
        played = t.groupby("name")["game_date"].nunique()
    else:
        played = pd.Series(dtype=int)
    inj = getattr(eng.data, "injuries", None)
    hurt = []
    if inj is not None and len(inj):
        team_ids = eng.data.players.index[eng.data.players["nba_team"] == team]
        for pid in inj.index.intersection(team_ids):
            if pid == me:
                continue
            r = inj.loc[pid]
            ret = r["return_date"]
            hurt.append({"name": names[pid], "status": str(r.get("status_text", "") or r["kind"]),
                         "return": None if pd.isna(ret) else str(pd.Timestamp(ret).date()),
                         "games_played_this_season": int(played.get(names[pid], 0))})
    out["injured_teammates"] = hurt
    return out


def player_card(eng: TradeEngine, pid: str, *, logs, ids, perceived: dict, playoff_games: dict) -> dict:
    P = eng.data.players
    inj = getattr(eng.data, "injuries", None)
    injury = None
    if inj is not None and pid in inj.index:
        r = inj.loc[pid]
        injury = {"status": str(r.get("status_text", "")), "return": None if pd.isna(r["return_date"])
                  else str(pd.Timestamp(r["return_date"]).date())}
    dur = getattr(eng.data, "durability", None)
    games = _logs_for(logs, ids, pid)
    team = str(P.loc[pid, "nba_team"])
    return {
        "id": pid, "name": P.loc[pid, "name"], "nba_team": team, "positions": str(P.loc[pid, "yahoo_positions"]),
        "yahoo_status": P.loc[pid, "injury_status"] or "", "injury": injury,
        "rank_rest_of_season_value": int(eng.market.rank(ascending=False).get(pid, 0)) or None,
        "perceived_rank": {k: (int(v[pid]) if pid in v.index and pd.notna(v[pid]) else None) for k, v in perceived.items()},
        "this_season": per_game(eng.data.stats["season_total"], pid),
        "yahoo_rest_of_season_projection": per_game(eng.data.stats[ROS], pid),
        "preseason_projection": per_game(eng.data.stats["preseason"], pid),
        "durability_rate": _r(dur.loc[pid, "rate"], 2) if dur is not None and pid in dur.index else None,
        "form": form(games), "playoff_week_games": playoff_games.get(pid),
        "nba_team_context": team_context(eng, logs, ids, team, pid),
    }


def news_items(store: dict, names: set[str], teams: set[str], since: str, limit: int = 25) -> list[dict]:
    out = []
    for it in store.get("items", {}).values():
        a = it.get("analysis")
        if not a or (it.get("published") or "") < since:
            continue
        if a.get("player") in names or it.get("player_name") in names or it.get("player_team") in teams \
                or any(n in names for n in (a.get("beneficiaries") or []) + (a.get("hurt") or [])):
            out.append({"date": (it.get("published") or "")[:10], "player": a.get("player") or it.get("player_name"),
                        "team": it.get("player_team"), "type": a.get("type"), "status": a.get("status"),
                        "return_estimate": a.get("return_estimate"), "summary": a.get("summary_tr"),
                        "beneficiaries": a.get("beneficiaries"), "hurt": a.get("hurt")})
    return sorted(out, key=lambda x: x["date"], reverse=True)[:limit]


def build_packet(eng: TradeEngine, team_a: str, team_b: str, give_a, give_b, *, strategies: tuple, scenarios: list,
                 counters: list, logs: pd.DataFrame | None, news_store: dict, playoff_games: dict,
                 live_adds_left: int | None = None) -> dict:
    """Claude'a giden veri paketi (yalnız sayılar ve kısa metinler)."""
    lg, P = eng.league, eng.data.players
    ids = match_ids(logs, P) if logs is not None and len(logs) else None
    perceived = {"by_season_box_score": perceived_ranks(eng, "season_total"), "by_preseason": perceived_ranks(eng, "preseason")}
    ranks = eng.market.rank(ascending=False)

    def roster(tid: str) -> list[dict]:
        il = lg.injury_rosters[tid]
        rows = [{"id": p, "name": P.loc[p, "name"], "positions": str(P.loc[p, "yahoo_positions"]),
                 "status": P.loc[p, "injury_status"] or "", "on_IL": p in il,
                 "il_return": str(eng.return_day(p)) if p in il and eng.return_day(p) else None,
                 "rank_rest_of_season_value": int(ranks.get(p, 0)) or None} for p in lg.rosters[tid]]
        return sorted(rows, key=lambda r: r["rank_rest_of_season_value"] or 9999)

    def cat_ranks(mode: str, tid: str) -> dict:
        r = eng.before[mode].ranks.loc[tid]
        return {CATEGORY_LABELS[c]: _r(r[c], 1) for c in CATEGORIES}

    cards = lambda ps: [player_card(eng, p, logs=logs, ids=ids, perceived=perceived, playoff_games=playoff_games)
                        for p in ps]
    names = {P.loc[p, "name"] for p in [*give_a, *give_b]}
    teams = {str(P.loc[p, "nba_team"]) for p in [*give_a, *give_b]}
    since = (eng.data.as_of - dt.timedelta(days=14)).isoformat()
    settings = {k: v for k, v in lg.settings.items() if k in (
        "Waiver Time", "Waiver Type", "Max Acquisitions per Week", "Playoffs", "Trade Review", "Trade End Date",
        "Roster Positions")}
    return {
        "today": str(eng.data.as_of), "league": {"name": lg.name, "teams": len(lg.teams), "roster_capacity": lg.capacity,
                                                 "il_slots": eng.config.unverified.il_slots, "settings": settings,
                                                 "your_adds_left_this_week": live_adds_left},
        "you": {"team": lg.teams[team_a], "strategy": strategies[0].name,
                "category_ranks_rest_of_season": cat_ranks("remaining_games_projection", team_a),
                "category_ranks_this_season": cat_ranks("season_total", team_a), "roster": roster(team_a)},
        "opponent": {"team": lg.teams[team_b], "strategy_assumed": strategies[1].name,
                     "category_ranks_rest_of_season": cat_ranks("remaining_games_projection", team_b),
                     "roster": roster(team_b)},
        "trade": {"you_give": cards(give_a), "you_get": cards(give_b)},
        "model": {
            "note": "Deltas are expected categories won per week vs the average opponent (9 = all); win = P(5+ "
                    "categories) change in points. 'returns' = IL return timeline after the trade (who returns, who is "
                    "cut; self_cut = the returning player himself is not good enough to play). 'incoming' = a player "
                    "you receive gets cut.",
            "scenarios_by_stat_basis": scenarios,
        },
        "counter_offer_candidates": counters,
        "news_last_14_days": news_items(news_store, names, teams, since),
    }


# ----------------------------------------------------------------- Claude ve saklama
def generate(packet: dict, *, client=None, model: str | None = None) -> tuple[dict | None, dict, str | None]:
    """Paket → (rapor | None, kullanım, hata). İstemci verilmezse ``.env``'deki anahtarla kurulur."""
    model = model or model_name()
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    kwargs = {}
    if model in ("claude-opus-5-5", "claude-sonnet-5-5"):
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = client.beta.messages.create(
        model=model, max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(packet, ensure_ascii=False, default=str)}], **kwargs)
    u = response.usage
    usage = {"model": response.model, "input": u.input_tokens, "output": u.output_tokens,
             "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
             "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0, "stop_reason": response.stop_reason}
    if response.stop_reason == "refusal":
        return None, usage, "Model bu isteği yanıtlamadı."
    if response.stop_reason == "max_tokens":
        return None, usage, "Yanıt uzunluk sınırına takıldı."
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        return None, usage, "Yanıt okunamadı."
    return report, usage, None


def cost(usage: dict) -> float:
    p = PRICES.get(usage.get("model", ""), PRICES["claude-opus-5-5"])
    return (usage["input"] * p[0] + usage["output"] * p[1] + usage["cache_read"] * p[2]
            + usage["cache_write"] * p[3]) / 1e6


def report_key(fingerprint: str, league: str, body: dict) -> str:
    keep = {k: body.get(k) for k in ("team_a", "team_b", "give_a", "give_b", "strategy_a", "strategy_b", "injuries")}
    keep["give_a"], keep["give_b"] = sorted(keep["give_a"] or []), sorted(keep["give_b"] or [])
    raw = json.dumps({"fp": fingerprint, "lg": league, **keep}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ReportStore:
    """Raporlar dosyada (``trade_reports.json``), üretim arka plan iş parçacığında; anahtar başına tek iş."""

    def __init__(self, directory: str | Path):
        self.path = Path(directory) / FILE
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, key: str) -> dict | None:
        with self.lock:
            if key in self.jobs:
                return self.jobs[key]
            saved = self._load().get(key)
        return {"status": "done", **saved} if saved else None

    def start(self, key: str, packet: dict, meta: dict, *, client=None, model: str | None = None) -> dict:
        with self.lock:
            if self.jobs.get(key, {}).get("status") == "running":
                return self.jobs[key]
            self.jobs[key] = {"status": "running", "key": key}
        threading.Thread(target=self._run, args=(key, packet, meta, client, model), daemon=True).start()
        return {"status": "running", "key": key}

    def _run(self, key, packet, meta, client, model) -> None:
        try:
            report, usage, error = generate(packet, client=client, model=model)
        except Exception as e:                                   # ağ, kota, anahtar: kullanıcıya iletilir
            report, usage, error = None, None, f"Analiz alınamadı: {e.__class__.__name__}: {e}"[:300]
        if report is None:
            with self.lock:
                self.jobs[key] = {"status": "error", "key": key, "error": error}
            return
        record = {"key": key, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                  "model": usage["model"], "cost": round(cost(usage), 4), "usage": usage, **meta, "report": report}
        with self.lock:
            saved = self._load()
            saved[key] = record
            for old in sorted(saved, key=lambda k: saved[k].get("created_at", ""))[:-KEEP]:
                del saved[old]
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            self.jobs.pop(key, None)


def available() -> bool:
    return load_env_key()
