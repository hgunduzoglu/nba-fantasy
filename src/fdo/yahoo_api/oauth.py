"""Yahoo OAuth 2.0 (yetkilendirme kodu akışı) ve token saklama (README §13.7).

Uygulama kimlik bilgileri (developer.yahoo.com → "Create an App", Fantasy Sports: Read)
``YAHOO_CLIENT_ID`` / ``YAHOO_CLIENT_SECRET`` ortam değişkenlerinden ya da
``~/.fdo/yahoo_app.json`` dosyasından okunur. Token'lar ``~/.fdo/yahoo_token.json``'da durur;
ikisi de repo dışındadır ve hiçbir çıktıya yazılmaz.

Akış: ``authorize_url`` → kullanıcı tarayıcıda onaylar ve kodu kopyalar (``redirect_uri=oob``)
→ ``exchange_code`` → süre dolunca ``refresh``.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
REDIRECT_URI = "oob"
DEFAULT_DIR = Path.home() / ".fdo"

#: ``post(url, headers, form) -> dict`` — testlerde sahte taşıyıcı verilir.
PostFn = Callable[[str, dict, dict], dict]


class YahooAuthError(RuntimeError):
    pass


@dataclass
class AppCredentials:
    client_id: str
    client_secret: str

    @classmethod
    def load(cls, path: Path | None = None) -> "AppCredentials":
        cid, secret = os.environ.get("YAHOO_CLIENT_ID"), os.environ.get("YAHOO_CLIENT_SECRET")
        if cid and secret:
            return cls(cid, secret)
        path = path or DEFAULT_DIR / "yahoo_app.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data["client_id"], data["client_secret"])
        raise YahooAuthError("Yahoo uygulama bilgisi yok: YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET ya da "
                             f"{path} (client_id, client_secret)")

    def basic_auth(self) -> str:
        return "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()


@dataclass
class Token:
    access_token: str
    refresh_token: str
    expires_at: float

    def expired(self, margin: float = 60.0) -> bool:
        return time.time() >= self.expires_at - margin


class TokenStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_DIR / "yahoo_token.json"

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        return Token(**json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(token)), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def authorize_url(creds: AppCredentials) -> str:
    q = urllib.parse.urlencode({"client_id": creds.client_id, "redirect_uri": REDIRECT_URI,
                                "response_type": "code", "language": "en-us"})
    return f"{AUTH_URL}?{q}"


def _token_from(resp: dict, old_refresh: str | None = None) -> Token:
    if "access_token" not in resp:
        raise YahooAuthError(f"Token alınamadı: {resp.get('error_description') or resp.get('error') or resp}")
    return Token(access_token=resp["access_token"], refresh_token=resp.get("refresh_token") or old_refresh or "",
                 expires_at=time.time() + float(resp.get("expires_in", 3600)))


def exchange_code(creds: AppCredentials, code: str, post: PostFn) -> Token:
    resp = post(TOKEN_URL, {"Authorization": creds.basic_auth()},
                {"grant_type": "authorization_code", "redirect_uri": REDIRECT_URI, "code": code.strip()})
    return _token_from(resp)


def refresh(creds: AppCredentials, token: Token, post: PostFn) -> Token:
    resp = post(TOKEN_URL, {"Authorization": creds.basic_auth()},
                {"grant_type": "refresh_token", "redirect_uri": REDIRECT_URI, "refresh_token": token.refresh_token})
    return _token_from(resp, token.refresh_token)


class TokenProvider:
    """Geçerli access token; gerekirse yeniler ve saklar."""

    def __init__(self, creds: AppCredentials, store: TokenStore, post: PostFn):
        self.creds, self.store, self.post = creds, store, post

    def access_token(self) -> str:
        tok = self.store.load()
        if tok is None:
            raise YahooAuthError("Yahoo'ya bağlanılmadı: önce yetkilendirme kodunu girin")
        if tok.expired():
            tok = refresh(self.creds, tok, self.post)
            self.store.save(tok)
        return tok.access_token
