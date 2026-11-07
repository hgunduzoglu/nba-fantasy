"""Haberler ve rol değişimleri (README §13.24–13.25): lige göre etiketlenmiş haber olayları, sakatlıkta rol değişimi
tablosu ve arka planda haber yenileme."""

from __future__ import annotations

import datetime as dt
from typing import Callable

from fastapi import FastAPI, HTTPException

from fdo.api.jobs import Job
from fdo.api.serialize import clean
from fdo.api.state import AppState
from fdo.ingest.nba_logs import refresh_season
from fdo.inseason import news
from fdo.inseason.fixtures import opponent as fixture_opponent
from fdo.inseason.roles import resolver

ROLE_MIN_MINUTES = 2.0          # tabloda gösterilecek en küçük (küçültülmüş) dakika farkı


def refresh_news(state: AppState, log: Callable[[str], None]) -> str:
    res = news.refresh(state.data_dir, state.data(True).players, log=log)
    notes = f" ({'; '.join(res['notes'])})" if res["notes"] else ""
    return f"Haberler: {res['new']} yeni, {res['analyzed']} analiz edildi{notes}"


def refresh_logs(state: AppState) -> str:
    season = next(iter(state.data(True).leagues.values())).config.league.season
    return refresh_season(state.data_dir, season)


def register(app: FastAPI, state: AppState) -> Job:
    job = Job()

    @app.get("/api/news/status")
    def news_status():
        store = news.load_store(state.data_dir)
        items = store["items"].values()
        week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
        return clean({**job.status(), "fetched_at": store.get("fetched_at"), "items": len(store["items"]),
                      "analyzed": sum(1 for i in items if i.get("analysis")), "model": news.model_name(),
                      "has_key": news.load_env_key(), "cost_7d": news.cost(store["usage"], week_ago),
                      "cost_total": news.cost(store["usage"])})

    @app.post("/api/news/refresh")
    def news_refresh():
        if not job.start(lambda log: {"summary": refresh_news(state, log)}):
            raise HTTPException(409, "Haber yenileme zaten sürüyor")
        return job.status()

    @app.get("/api/leagues/{lid}/news")
    def league_news(lid: str, team: str, injuries: bool = True, days: int = 7):
        try:
            eng = state.engine(lid, injuries)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        if team not in eng.league.rosters:
            raise HTTPException(404, f"Takım yok: {team}")
        data = eng.data
        players = data.players
        resolve = resolver(players)
        owner = {p: t for t, r in eng.league.rosters.items() for p in r}
        lv = state.live(lid, injuries)
        waivers = lv.waivers if lv else {}
        weeks = state.weeks(lid, injuries)
        wk = weeks.week_of(data.as_of)
        opp = fixture_opponent(state.fixtures(), lid, team, wk) if wk else None

        def who(pid: str | None, name: str = "") -> dict:
            if pid is None:
                return {"id": None, "name": name, "owner": None, "owner_name": None, "nba_team": "", "status": ""}
            o = owner.get(pid)
            kind = "me" if o == team else "opp" if o and o == opp else "team" if o else "W" if pid in waivers else "FA"
            return {"id": pid, "name": players.loc[pid, "name"], "owner": kind,
                    "owner_name": eng.league.teams.get(o) if o else None, "nba_team": players.loc[pid, "nba_team"],
                    "status": players.loc[pid, "injury_status"] or "",
                    "waiver_until": waivers.get(pid) if pid in waivers else None}

        def by_name(name: str, team_hint: str = "") -> dict:
            return who(resolve(name, team_hint) or resolve(name), name)

        cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        store = news.load_store(state.data_dir)
        events = []
        for it in store["items"].values():
            when = it.get("published") or it["fetched_at"]
            if when < cut:
                continue
            a = it.get("analysis")
            name, nba = (a["player"], a["team"]) if a else (it["player_name"], it["player_team"])
            main = by_name(name, nba) if name else None
            ben = [by_name(n, nba) for n in (a["beneficiaries"] if a else [])]
            hurt = [by_name(n, nba) for n in (a["hurt"] if a else [])]
            people = [x for x in [main, *ben, *hurt] if x]
            tags = sorted({t for t, ok in (
                ("mine", any(x["owner"] == "me" for x in people)),
                ("opp", any(x["owner"] == "opp" for x in people)),
                ("fa", any(x["owner"] in ("FA", "W") for x in ben)
                 or (main is not None and main["owner"] in ("FA", "W") and a is not None and a["impact"] > 0)),
            ) if ok})
            events.append({"id": it["id"], "source": it["source"], "url": it["url"], "published": when,
                           "headline": it["headline"], "body": it["body"], "analyzed": a is not None,
                           "type": a["type"] if a else None, "status": a["status"] if a else None,
                           "return_estimate": (a["return_estimate"] or None) if a else None,
                           "games_out": a["games_out"] if a and a["games_out"] >= 0 else None,
                           "impact": a["impact"] if a else None, "summary": a["summary_tr"] if a else None,
                           "player": main, "beneficiaries": ben, "hurt": hurt, "tags": tags})
        events.sort(key=lambda e: e["published"], reverse=True)
        roles = []
        for pid, r in state.roles(injuries).items():
            if pid not in eng.index:
                continue
            w = who(pid)
            if w["owner"] not in ("me", "opp", "FA", "W") or abs(r.delta["minutes"]) < ROLE_MIN_MINUTES:
                continue
            roles.append({"player": w, "team": r.team, "absent": [players.loc[p, "name"] for p in r.absent],
                          "until": r.until if r.until < dt.date.max else None, "n_without": r.n_without,
                          "n_with": r.n_with, "delta": {k: r.delta[k] for k in
                                                        ("minutes", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov")},
                          "raw_minutes": r.raw["minutes"]})
        roles.sort(key=lambda r: (r["player"]["owner"] != "me", -abs(r["delta"]["minutes"])))
        return clean({"events": events, "roles": roles, "opponent": opp,
                      "opponent_name": eng.league.teams.get(opp) if opp else None})

    return job
