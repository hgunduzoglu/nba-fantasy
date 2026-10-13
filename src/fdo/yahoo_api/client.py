"""Yahoo Fantasy Sports API istemcisi (README §13.7). Yalnızca okuma.

JSON çıktısı (``?format=json``) iç içe "sayısal anahtarlı sözlük" yapısındadır; ayrıştırıcılar
savunmacıdır. Canlı draft sırasında henüz yapılmamış pick'ler ``player_key`` içermez.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from fdo.yahoo_api.oauth import TokenProvider

API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
ATTRIBUTION = "Veri: Yahoo Fantasy Sports API"

#: ``get(url, headers) -> dict``
GetFn = Callable[[str, dict], dict]


class YahooApiError(RuntimeError):
    pass


def urllib_get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise YahooApiError(f"HTTP {e.code}: {e.read()[:300]!r}") from e


def urllib_post(url: str, headers: dict, form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, headers={**headers,
                                                         "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise YahooApiError(f"HTTP {e.code}: {body[:300]}") from e


@dataclass(frozen=True)
class DraftResult:
    pick: int
    round: int
    team_key: str
    player_key: str | None


def _numbered(d) -> list:
    """``{"0": {...}, "1": {...}, "count": n}`` → değer listesi (sayısal anahtar sırasıyla)."""
    if isinstance(d, list):
        return d
    if not isinstance(d, dict):
        return []
    keys = sorted((k for k in d if str(k).isdigit()), key=int)
    return [d[k] for k in keys]


def _merge_list(parts) -> dict:
    """Yahoo'nun ``[{"a": 1}, {"b": 2}, ...]`` parçalı nesnelerini tek sözlükte birleştirir."""
    out: dict = {}
    for p in parts if isinstance(parts, list) else [parts]:
        if isinstance(p, dict):
            out.update(p)
        elif isinstance(p, list):
            out.update(_merge_list(p))
    return out


def parse_draft_results(payload: dict) -> tuple[dict, list[DraftResult]]:
    """``league/{key}/draftresults`` → (lig meta, pick'ler)."""
    league = payload.get("fantasy_content", {}).get("league")
    if not isinstance(league, list) or not league:
        raise YahooApiError("Beklenmeyen yanıt: fantasy_content.league yok")
    meta = _merge_list(league[0])
    rest = _merge_list(league[1:])
    out = []
    for item in _numbered(rest.get("draft_results", {})):
        r = item.get("draft_result", item) if isinstance(item, dict) else {}
        if "pick" not in r:
            continue
        out.append(DraftResult(pick=int(r["pick"]), round=int(r.get("round", 0)), team_key=str(r.get("team_key", "")),
                               player_key=str(r["player_key"]) if r.get("player_key") else None))
    return meta, sorted(out, key=lambda d: d.pick)


def player_id_from_key(player_key: str) -> str:
    """``"466.p.5352"`` → ``"y_5352"`` (``fdo.ingest.yahoo.internal_id`` ile aynı biçim)."""
    return f"y_{str(player_key).rsplit('.p.', 1)[-1]}"


class YahooClient:
    def __init__(self, tokens: TokenProvider | None, get: GetFn = urllib_get):
        self.tokens = tokens
        self._get = get

    def get(self, path: str) -> dict:
        sep = "&" if "?" in path else "?"
        headers = {"Authorization": f"Bearer {self.tokens.access_token()}"} if self.tokens else {}
        return self._get(f"{API_BASE}/{path.lstrip('/')}{sep}format=json", headers)

    def draft_results(self, league_key: str) -> tuple[dict, list[DraftResult]]:
        return parse_draft_results(self.get(f"league/{league_key}/draftresults"))
