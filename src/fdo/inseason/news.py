"""Haber analizi (README §13.25): CBS (RotoWire) oyuncu haberleri ve ESPN NBA haberleri Claude ile yapılandırılmış
fantezi olaylarına çevrilir.

* **Kaynaklar**: CBS fantezi oyuncu haberleri (genel akışın ilk sayfası = son 30 not, ~4–8 saat; 8 Kasım 2026'dan
  beri ikinci sayfayı ve sakatlık akışını da site otomatik istemcilere 406 ile reddediyor) ve ESPN NBA haber akışı
  (başlık + özet, 50). Boşluk kalmaması için sık yenilenmeli (``scripts/news_refresh.py``, 2 saatte bir). Her yenilemede yeni olanlar eklenir; haber
  kimliği bağlantısıdır, bir kez saklanır ve bir kez analiz edilir. 21 günden eskiler silinir.
* **Süzme** (model çağrısından önce, ücretsiz): CBS haberi Yahoo oyuncu havuzundaki bir oyuncuya eşleşmeli ve başlığında
  rol/sakatlık/takas sinyali olmalı (``SIGNAL``; "Scores 30 in loss" gibi maç özetleri analiz edilmez, listede kalır);
  ESPN haberinin başlığında ya da özetinde havuzdaki bir oyuncunun tam adı geçmeli.
* **Model**: ``claude-opus-5-5`` (``FDO_NEWS_MODEL`` ile değişir), efor ``low``, JSON şemalı yapılandırılmış çıktı,
  30 haberlik partiler, sabit sistem talimatı önbellekli, sunucu tarafı yedek model (``fallbacks: "default"``). Bir
  yenilemede en çok ``max_items`` haber analiz edilir (en yeniler önce). Anahtar ``ANTHROPIC_API_KEY`` ortam
  değişkeninden ya da depo kökündeki ``.env`` dosyasından okunur (git dışı).
* **Çıktı**: olay türü, durum, tahmini dönüş günü, kazanan / kaybeden takım arkadaşları, fantezi etkisi (−2…+2) ve
  Türkçe tek cümle özet. Her çağrının token kullanımı kaydedilir; maliyet tahmini bu kayıttan.
"""

from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import os
import re
from pathlib import Path
from typing import Callable

from fdo.config import REPO_ROOT

FILE = "news.json"
CBS = "https://www.cbssports.com/fantasy/basketball/players/news/{feed}/{page}"
CBS_PAGES = (("all", 1),)     # durağan erişime açık tek sayfa (diğerleri 406)
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=50"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
MODEL = "claude-opus-5-5"
BATCH = 30
KEEP_DAYS = 21
#: $/1M token (Ekim 2026, Anthropic birinci taraf): girdi, çıktı, önbellek okuma, önbellek yazma (5 dk, ×1.25).
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.20, 5.0), "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
          "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125)}
#: Başlıkta bunlardan biri yoksa CBS haberi maç özeti sayılır (modele gönderilmez).
SIGNAL = re.compile(r"\b(out|questionable|doubtful|probable|ruled|return|back|injur|sidelin|miss|start|bench|rotation|"
                    r"minutes|role|trade|deal|acquir|waive|sign|suspen|rest|available|clear|status|upgrade|downgrade|"
                    r"game-time|surgery|sprain|strain|ankle|knee|foot|hamstring|calf|back|illness|personal|g league|"
                    r"assign|recall|two-way|timeline|expected|reserve|unavailable|absence|setback|limit|good to go|"
                    r"suit up|active|won't|will play|to play|lineup|playing time|healthy|inactive)", re.I)
TYPES = ("injury", "return", "role_up", "role_down", "lineup", "trade", "trade_rumor", "signing", "waived",
         "suspension", "rest", "performance", "other")
STATUSES = ("out", "doubtful", "questionable", "probable", "available", "unknown")

SYSTEM = """You turn NBA news into structured events for Yahoo head-to-head 9-category fantasy basketball \
(FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO).

You receive a JSON list of news items. Each has an id, a source, the publication time, the main player (may be empty \
for general articles) with team, a headline and the text. Return exactly one event per item, in the same order, with \
the item's id.

Fields:
- player: the main player as written in the item ("" if none). team: NBA abbreviation ("" if unknown).
- type: injury (new or ongoing absence), return (cleared / back), role_up (more minutes, starting, bigger usage), \
role_down, lineup (starting lineup or rotation note without a clear direction), trade (completed), trade_rumor, \
signing, waived, suspension, rest (load management, one game), performance (game recap, no role change), other \
(not fantasy relevant).
- status: the main player's availability for the next game: out, doubtful, questionable, probable, available, unknown.
- return_estimate: expected first game back as YYYY-MM-DD if the item gives or clearly implies a date or time span \
(resolve weekdays and "next week" against the publication time); otherwise "".
- games_out: expected games missed from now if stated or clearly implied, else -1.
- beneficiaries: teammates (full names) the item says or strongly implies will gain minutes, starts or usage. \
hurt: players who will lose them (for a return, the players pushed back). Only players named in the item; [] if none.
- impact: fantasy value change for the main player over the next two weeks: -2 big loss, -1 loss, 0 none, 1 gain, \
2 big gain.
- summary_tr: one Turkish sentence of at most 140 characters, fantasy-actionable (who, what, until when, who \
benefits). Keep player names as written.

Do not invent facts beyond the item. Be concise."""

SCHEMA = {
    "type": "object",
    "properties": {"events": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "player": {"type": "string"}, "team": {"type": "string"},
            "type": {"type": "string", "enum": list(TYPES)}, "status": {"type": "string", "enum": list(STATUSES)},
            "return_estimate": {"type": "string"}, "games_out": {"type": "integer"},
            "beneficiaries": {"type": "array", "items": {"type": "string"}},
            "hurt": {"type": "array", "items": {"type": "string"}},
            "impact": {"type": "integer"}, "summary_tr": {"type": "string"},
        },
        "required": ["id", "player", "team", "type", "status", "return_estimate", "games_out", "beneficiaries", "hurt",
                     "impact", "summary_tr"],
        "additionalProperties": False}}},
    "required": ["events"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------ depolama
def load_store(directory: str | Path) -> dict:
    path = Path(directory) / FILE
    if not path.exists():
        return {"items": {}, "usage": [], "fetched_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


def save_store(directory: str | Path, store: dict) -> None:
    path = Path(directory) / FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def prune(store: dict, now: dt.datetime) -> None:
    cut = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
    store["items"] = {k: v for k, v in store["items"].items() if (v.get("published") or v["fetched_at"]) >= cut}


# ------------------------------------------------------------------ kaynaklar
_LI = re.compile(r"<li>\s*<div class=\"row\">(.*?)</li>", re.S)
_PLAYER = re.compile(r'<p><a href="/nba/players/(\d+)/[^"]*">([^<]+)</a>\s*<span>\s*([A-Z,]*)\s*\|\s*([A-Z]{2,4})\s*</span>')
_TIME = re.compile(r'<time class="eyebrow">([^<]*)</time>')
_HEAD = re.compile(r'<h4><a href="([^"]+)">([^<]+)</a></h4>')
_BODY = re.compile(r'<div class="latest-updates">(.*?)</div>', re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return " ".join(html_lib.unescape(_TAG.sub(" ", s)).split())


def published_at(age: str, now: dt.datetime) -> str:
    """CBS zaman metni (``15M ago``, ``2H ago``, ``1D ago``, ``Nov 6``) → ISO zaman (UTC)."""
    a = age.strip()
    if m := re.match(r"(\d+)\s*([MHD])\s*ago", a, re.I):
        unit = {"M": "minutes", "H": "hours", "D": "days"}[m.group(2).upper()]
        return (now - dt.timedelta(**{unit: int(m.group(1))})).isoformat(timespec="minutes")
    if m := re.match(r"([A-Za-z]{3})\w*\.?\s+(\d{1,2})", a):
        month = dt.datetime.strptime(m.group(1)[:3].title(), "%b").month
        d = dt.datetime(now.year, month, int(m.group(2)), 12, tzinfo=dt.timezone.utc)
        return (d.replace(year=now.year - 1) if d > now + dt.timedelta(days=1) else d).isoformat(timespec="minutes")
    return ""


def parse_cbs(page: str, now: dt.datetime) -> list[dict]:
    out = []
    for block in _LI.findall(page):
        head, body = _HEAD.search(block), _BODY.search(block)
        if not head:
            continue
        pl, age = _PLAYER.search(block), _TIME.search(block)
        url = "https://www.cbssports.com" + head.group(1) if head.group(1).startswith("/") else head.group(1)
        out.append({"id": url, "source": "cbs", "url": url, "player_name": _text(pl.group(2)) if pl else "",
                    "position": pl.group(3) if pl else "", "player_team": pl.group(4) if pl else "",
                    "age_text": age.group(1) if age else "", "published": published_at(age.group(1), now) if age else "",
                    "headline": _text(head.group(2)), "body": _text(body.group(1)) if body else ""})
    return out


def parse_espn(doc: dict) -> list[dict]:
    out = []
    for a in doc.get("articles", []):
        url = ((a.get("links") or {}).get("web") or {}).get("href") or f"espn:{a.get('id')}"
        out.append({"id": url, "source": "espn", "url": url, "player_name": "", "position": "", "player_team": "",
                    "age_text": "", "published": a.get("published", ""), "headline": a.get("headline", ""),
                    "body": a.get("description", "")})
    return out


def fetch_all(get: Callable[[str], object] | None = None) -> tuple[list[dict], list[str]]:
    """CBS akışları + ESPN; ``get(url)`` → ``requests.Response`` benzeri (test için değiştirilebilir)."""
    import time

    import requests

    session = requests.Session()
    session.headers.update(HEADERS)
    get = get or (lambda url: session.get(url, timeout=20))
    now = dt.datetime.now(dt.timezone.utc)
    items, notes = [], []
    for feed, page in CBS_PAGES:
        r = get(CBS.format(feed=feed, page="" if page == 1 else f"{page}/"))
        if getattr(r, "status_code", 200) != 200:
            notes.append(f"CBS {feed} {page}: HTTP {r.status_code}")
            continue
        items += parse_cbs(r.text, now)
        time.sleep(2.5)
    r = get(ESPN)
    if getattr(r, "status_code", 200) == 200:
        items += parse_espn(r.json())
    else:
        notes.append(f"ESPN: HTTP {r.status_code}")
    return list({i["id"]: i for i in items}.values()), notes


# ------------------------------------------------------------------ süzme ve analiz
def relevant(item: dict, resolve: Callable[[str, str], str | None], names: set[str]) -> bool:
    """CBS: oyuncu havuzda ve başlıkta sinyal var; ESPN: başlık/özette havuzdaki bir oyuncunun tam adı geçiyor
    (``names``: ``normalize_name`` ile iki ya da daha çok kelimelik adlar)."""
    from fdo.ingest.load import normalize_name

    if item["source"] == "cbs":
        return resolve(item["player_name"], item["player_team"]) is not None and bool(SIGNAL.search(item["headline"]))
    words = normalize_name(f"{item['headline']} {item['body']}").split()
    grams = {" ".join(words[i:i + k]) for k in (2, 3) for i in range(len(words) - k + 1)}
    return bool(grams & names)


def load_env_key() -> bool:
    """``ANTHROPIC_API_KEY`` yoksa depo kökündeki ``.env``'den okur (değer hiçbir yere yazılmaz)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ANTHROPIC_API_KEY" and v.strip():
                os.environ["ANTHROPIC_API_KEY"] = v.strip().strip('"').strip("'")
                return True
    return False


def model_name() -> str:
    return os.environ.get("FDO_NEWS_MODEL", MODEL)


def _payload(items: list[dict]) -> str:
    rows = [{"id": str(k), "source": i["source"], "published": i.get("published", ""),
             "player": i["player_name"], "team": i["player_team"], "headline": i["headline"], "text": i["body"]}
            for k, i in enumerate(items)]
    return json.dumps(rows, ensure_ascii=False)


def analyze_batch(client, items: list[dict], model: str) -> tuple[list[dict | None], dict]:
    """Bir parti → her habere bir olay (yanıtta olmayan ``None``) ve token kullanımı."""
    kwargs = {}
    if model in ("claude-opus-5-5", "claude-sonnet-5-5"):
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = client.beta.messages.create(
        model=model, max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": _payload(items)}], **kwargs)
    u = response.usage
    usage = {"model": response.model, "input": u.input_tokens, "output": u.output_tokens,
             "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
             "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0, "items": len(items),
             "stop_reason": response.stop_reason}
    if response.stop_reason in ("refusal", "max_tokens"):
        return [None] * len(items), usage
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        events = json.loads(text)["events"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return [None] * len(items), usage
    by_id = {e["id"]: e for e in events if isinstance(e, dict)}
    return [by_id.get(str(k)) for k in range(len(items))], usage


def refresh(directory: str | Path, players, *, fetch: Callable[[], tuple[list[dict], list[str]]] | None = None,
            client=None, max_items: int = 120, log: Callable[[str], None] = lambda s: None) -> dict:
    """Yeni haberleri ekler ve analiz edilmemiş ilgili haberleri (en yeniler önce, en çok ``max_items``) analiz eder.
    ``players``: Yahoo oyuncu tablosu (``name``, ``nba_team``). Dönüş: özet sayılar ve notlar."""
    from fdo.inseason.roles import resolver
    from fdo.ingest.load import normalize_name

    store = load_store(directory)
    now = dt.datetime.now(dt.timezone.utc)
    items, notes = (fetch or fetch_all)()
    new = 0
    for it in items:
        if it["id"] not in store["items"]:
            store["items"][it["id"]] = {**it, "fetched_at": now.isoformat(timespec="minutes"), "analysis": None}
            new += 1
    store["fetched_at"] = now.isoformat(timespec="minutes")
    prune(store, now)
    resolve = resolver(players)
    names = {n for n in map(normalize_name, players["name"]) if len(n.split()) >= 2}
    pending = [i for i in store["items"].values() if i.get("analysis") is None and not i.get("skipped")
               and relevant(i, resolve, names)]
    chosen = {i["id"] for i in pending}
    for i in store["items"].values():
        if i.get("analysis") is None and i["id"] not in chosen:
            i["skipped"] = True
    pending.sort(key=lambda i: i.get("published") or i["fetched_at"], reverse=True)
    pending = pending[:max_items]
    analyzed = 0
    if pending and (client is not None or load_env_key()):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        model = model_name()
        for k in range(0, len(pending), BATCH):
            part = pending[k:k + BATCH]
            log(f"Haber analizi: {k + len(part)}/{len(pending)}")
            events, usage = analyze_batch(client, part, model)
            store["usage"].append({"at": now.isoformat(timespec="minutes"), **usage})
            for it, ev in zip(part, events):
                if ev is not None:
                    it["analysis"] = ev
                    analyzed += 1
            save_store(directory, store)
    elif pending:
        notes.append("ANTHROPIC_API_KEY yok: haberler analiz edilmeden saklandı.")
    save_store(directory, store)
    return {"fetched": len(items), "new": new, "pending": len(pending), "analyzed": analyzed, "notes": notes}


def cost(usage: list[dict], since: str = "") -> float:
    total = 0.0
    for u in usage:
        if u.get("at", "") < since:
            continue
        p = PRICES.get(u.get("model", ""), PRICES[MODEL])
        total += (u["input"] * p[0] + u["output"] * p[1] + u["cache_read"] * p[2] + u["cache_write"] * p[3]) / 1e6
    return total
