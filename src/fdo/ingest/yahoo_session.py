"""Yahoo oturumu: senkronizasyonun kullandığı ayrı Chrome profili.

Kullanıcı bu profilde bir kez Yahoo'ya giriş yapar (``scripts/yahoo_login.py``); senkronizasyon aynı
profili görünmez pencereyle açıp lig sayfalarını okur. Profil (çerezler) depo dışında, kullanıcının
yerel uygulama klasöründe durur; asla git'e girmez.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

LOGIN_URL = "https://login.yahoo.com/"
FANTASY_URL = "https://basketball.fantasysports.yahoo.com/nba"


def profile_dir() -> Path:
    """``FDO_YAHOO_PROFILE`` ya da ``%LOCALAPPDATA%/fdo/yahoo-chrome`` (Windows dışı: ``~/.fdo/yahoo-chrome``)."""
    if os.environ.get("FDO_YAHOO_PROFILE"):
        return Path(os.environ["FDO_YAHOO_PROFILE"])
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "fdo" / "yahoo-chrome" if base else Path.home() / ".fdo" / "yahoo-chrome"


def find_chrome() -> Path | None:
    """Kurulu Google Chrome; ``FDO_CHROME`` ile değiştirilebilir."""
    if os.environ.get("FDO_CHROME"):
        return Path(os.environ["FDO_CHROME"])
    candidates = [Path(os.environ.get(v, "")) / "Google" / "Chrome" / "Application" / "chrome.exe"
                  for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(v)]
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
    return Path(found) if found else None
