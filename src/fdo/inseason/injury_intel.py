"""Sakatlık analizi: kadrodaki sakat ya da belirsiz oyuncular için Claude'un web aramasıyla güncel durum özeti.

* **Kimler**: verilen takımların kadrosunda Yahoo durumu (O, INJ, Q, GTD, DTD, D, NA) ya da CBS sakatlık raporu satırı
  olan oyuncular.
* **Model**: ``claude-fable-5-2`` (``FDO_INJURY_MODEL`` ile değişir), sunucu tarafı web araması
  (``web_search_20260209``), JSON şemalı yapılandırılmış çıktı. Birkaç oyuncu bir çağrıda; sunucu aracı uzun sürerse
  (``pause_turn``) aynı konuşma sürdürülür.
* **Çıktı**: sakatlık, son raporun tarihi, resmi takvim, en erken ve en geç dönüş tahmini, güven, dakika kısıtlaması,
  B2B'de dinlendirilme beklentisi ve kaç hafta, tekrar riski, Türkçe tek cümle özet ve tarihli kaynaklar.
* **Kullanım**: yalnız gösterilir; modelin dönüş tarihleri CBS'ten gelir. Model kendi tahminleri ölçülmeden onları
  kullanmaz (B2B oranları maç kayıtlarından ölçülür, ``config/returns.yaml``).
* **Saklama**: veri dizininde ``injury_intel.json``; oyuncu başına son analiz, ``STALE_HOURS``'tan eski ya da CBS/Yahoo
  durumu değişmiş olanlar yenilenir. Her çağrının token ve arama sayısı kaydedilir; maliyet bu kayıttan.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Callable

FILE = "injury_intel.json"
MODEL = "claude-fable-5-2"
BATCH = 4
STALE_HOURS = 20
MAX_CONTINUE = 6
#: $/1M token: girdi, çıktı, önbellek okuma, önbellek yazma (5 dk). Web araması 1000 arama başına $10.
PRICES = {"claude-fable-5-2": (10.0, 50.0, 0.25, 12.5), "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
          "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0)}
SEARCH_PRICE = 10.0 / 1000
STATUSES = ("O", "INJ", "Q", "GTD", "DTD", "D", "NA")
LEVELS = ("low", "medium", "high")
FLAGS = ("none", "likely", "confirmed", "unknown")

SYSTEM = """You research the current injury situation of NBA players for a Yahoo head-to-head 9-category fantasy \
basketball manager (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO). The season is 2026-27.

You receive today's date and a JSON list of players. Each has an id, name, NBA team, the Yahoo status and the CBS \
injury-report row (injury, status text, earliest return date) when there is one.

For each player, search the web for the most recent reports about this injury (team announcements, beat writers, \
RotoWire/CBS/ESPN/The Athletic notes). Use only reports about the 2026-27 season: search results often surface older \
seasons' injuries for the same player, so check every report's date and ignore anything before October 2026. If you \
cannot find a current report, say so and fall back to the CBS row.

Return one entry per player, in the same order, with the player's id:
- injury: body part and type as reported (e.g. "left hamstring strain, grade 2").
- status: out | doubtful | questionable | probable | available | unknown.
- latest_report_date: YYYY-MM-DD of the newest report you used, or "".
- official_timeline: the team's or reporters' stated timeline in a few words (e.g. "re-evaluated in 4 weeks from Nov 8").
- return_earliest / return_latest: your estimated window for the first game back, YYYY-MM-DD, or "" if unknowable. \
Base it on the reported timeline and typical recovery for this injury, not on hope.
- return_confidence: low | medium | high.
- minutes_restriction: none | likely | confirmed | unknown, for the first games after the return.
- b2b_rest: none | likely | confirmed | unknown: will the team rest him on the second night of back-to-backs after \
the return (or already now, for an older or load-managed player)?
- b2b_rest_weeks: how many weeks after the return that rest is expected to last (0 if none).
- reinjury_risk: low | medium | high, from the injury type and the player's history (hamstring and high-ankle \
sprains re-aggravate often).
- summary_tr: one sentence in Turkish for the fantasy manager: what to expect and what to do.
- sources: up to 4 reports you used, each with url, title and date (YYYY-MM-DD or "").

Be factual and dated. Do not invent reports or dates; when unsure use "unknown" or "" and a low confidence."""

_STR = {"type": "string"}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["players"],
    "properties": {"players": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "injury", "status", "latest_report_date", "official_timeline", "return_earliest",
                     "return_latest", "return_confidence", "minutes_restriction", "b2b_rest", "b2b_rest_weeks",
                     "reinjury_risk", "summary_tr", "sources"],
        "properties": {
            "id": _STR, "injury": _STR,
            "status": {"type": "string", "enum": ["out", "doubtful", "questionable", "probable", "available", "unknown"]},
            "latest_report_date": _STR, "official_timeline": _STR, "return_earliest": _STR, "return_latest": _STR,
            "return_confidence": {"type": "string", "enum": list(LEVELS)},
            "minutes_restriction": {"type": "string", "enum": list(FLAGS)},
            "b2b_rest": {"type": "string", "enum": list(FLAGS)},
            "b2b_rest_weeks": {"type": "integer"},
            "reinjury_risk": {"type": "string", "enum": list(LEVELS)},
            "summary_tr": _STR,
            "sources": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                   "required": ["url", "title", "date"],
                                                   "properties": {"url": _STR, "title": _STR, "date": _STR}}}}}}}}


def model_name() -> str:
    return os.environ.get("FDO_INJURY_MODEL", MODEL)


def load_store(directory: str | Path) -> dict:
    path = Path(directory) / FILE
    if path.exists():
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(store, dict):
                return {"items": store.get("items") or {}, "usage": store.get("usage") or []}
        except json.JSONDecodeError:
            pass
    return {"items": {}, "usage": []}


def save_store(directory: str | Path, store: dict) -> None:
    path = Path(directory) / FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def candidates(engine, team_ids) -> list[dict]:
    """``team_ids`` kadrolarındaki sakat ya da belirsiz oyuncular: Yahoo durumu ve CBS satırıyla."""
    players = engine.data.players
    inj = getattr(engine.data, "injuries", None)
    out, seen = [], set()
    for tid in team_ids:
        for pid in engine.league.rosters.get(tid, ()):
            if pid in seen or pid not in players.index:
                continue
            status = str(players.loc[pid, "injury_status"] or "")
            cbs = None
            if inj is not None and pid in inj.index:
                r = inj.loc[pid]
                ret = r.get("return_date")
                cbs = {"injury": str(r.get("injury") or ""), "status_text": str(r.get("status_text") or ""),
                       "return_date": "" if ret is None or ret != ret else str(ret)[:10]}
            if status not in STATUSES and cbs is None:
                continue
            seen.add(pid)
            out.append({"id": pid, "name": str(players.loc[pid, "name"]), "team": str(players.loc[pid, "nba_team"] or ""),
                        "yahoo_status": status, "cbs": cbs, "fantasy_team": tid})
    return out


def signature(row: dict) -> str:
    """Analizi geçersiz kılan girdiler: Yahoo durumu ve CBS satırı."""
    return json.dumps([row.get("yahoo_status"), row.get("cbs")], sort_keys=True)


def stale(store: dict, row: dict, now: dt.datetime, hours: float = STALE_HOURS) -> bool:
    item = store["items"].get(row["id"])
    if not item or item.get("signature") != signature(row) or not item.get("analysis"):
        return True
    try:
        at = dt.datetime.fromisoformat(item["analyzed_at"])
    except (KeyError, ValueError):
        return True
    return now - at > dt.timedelta(hours=hours)


def _usage(response, model: str) -> dict:
    u = response.usage
    stu = getattr(u, "server_tool_use", None)
    return {"model": getattr(response, "model", model) or model, "input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "searches": (getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0}


def analyze_batch(client, rows: list[dict], model: str, today: dt.date) -> tuple[list[dict | None], dict]:
    """Bir parti → oyuncu başına analiz (yanıtta olmayan ``None``) ve toplam kullanım. Sunucu aracı ``pause_turn`` ile
    durursa konuşma aynı içerikle sürdürülür."""
    payload = json.dumps({"today": today.isoformat(), "players": [
        {"id": r["id"], "name": r["name"], "team": r["team"], "yahoo_status": r["yahoo_status"], "cbs": r["cbs"]}
        for r in rows]}, ensure_ascii=False)
    messages = [{"role": "user", "content": payload}]
    total = {"model": model, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "searches": 0,
             "players": len(rows), "calls": 0, "stop_reason": None}
    response = None
    for _ in range(MAX_CONTINUE):
        response = client.beta.messages.create(
            model=model, max_tokens=12000,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4 * len(rows)}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=messages)
        u = _usage(response, model)
        total["model"] = u["model"]
        for k in ("input", "output", "cache_read", "cache_write", "searches"):
            total[k] += u[k]
        total["calls"] += 1
        total["stop_reason"] = response.stop_reason
        if response.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": response.content}]
    if response is None or response.stop_reason in ("refusal", "max_tokens", "pause_turn"):
        return [None] * len(rows), total
    text = next((b.text for b in reversed(response.content) if getattr(b, "type", "") == "text"), "")
    try:
        found = json.loads(text)["players"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return [None] * len(rows), total
    by_id = {str(p.get("id")): p for p in found if isinstance(p, dict)}
    return [by_id.get(r["id"]) for r in rows], total


def refresh(directory: str | Path, rows: list[dict], *, client=None, max_players: int = 12, force: bool = False,
            today: dt.date | None = None, log: Callable[[str], None] = lambda s: None) -> dict:
    """``rows`` (``candidates``) içinden eskimiş olanları (en çok ``max_players``) analiz eder ve saklar."""
    store = load_store(directory)
    now = dt.datetime.now(dt.timezone.utc)
    today = today or now.date()
    pending = [r for r in rows if force or stale(store, r, now)][:max_players]
    analyzed = 0
    if pending:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        model = model_name()
        for k in range(0, len(pending), BATCH):
            part = pending[k:k + BATCH]
            log(f"Sakatlık analizi: {k + len(part)}/{len(pending)}")
            found, usage = analyze_batch(client, part, model, today)
            store["usage"].append({"at": now.isoformat(timespec="minutes"), **usage})
            for r, a in zip(part, found):
                if a is None:
                    continue
                store["items"][r["id"]] = {"name": r["name"], "team": r["team"], "signature": signature(r),
                                           "analyzed_at": now.isoformat(timespec="minutes"), "model": usage["model"],
                                           "yahoo_status": r["yahoo_status"], "cbs": r["cbs"], "analysis": a}
                analyzed += 1
            save_store(directory, store)
    return {"candidates": len(rows), "pending": len(pending), "analyzed": analyzed,
            "cost": round(cost(store["usage"][-((len(pending) + BATCH - 1) // BATCH):]) if pending else 0.0, 4)}


def cost(usage: list[dict]) -> float:
    total = 0.0
    for u in usage:
        p = PRICES.get(u.get("model", ""), PRICES[MODEL])
        total += (u["input"] * p[0] + u["output"] * p[1] + u["cache_read"] * p[2] + u["cache_write"] * p[3]) / 1e6
        total += u.get("searches", 0) * SEARCH_PRICE
    return total
