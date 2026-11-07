"""Senkronizasyon profiliyle normal bir Chrome penceresi açar; Yahoo'ya bir kez giriş yaparsın.

Pencere otomasyon bayrağı olmadan açılır (Yahoo girişi normal tarayıcıdaki gibi). Giriş yapıp
"Oturumu açık tut"u işaretle, lig sayfası açılınca pencereyi kapat. Çerezler depo dışındaki profil
klasöründe kalır (``fdo.ingest.yahoo_session.profile_dir``).

    python scripts/yahoo_login.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from urllib.parse import quote

from fdo.ingest.yahoo_session import FANTASY_URL, LOGIN_URL, find_chrome, profile_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait", action="store_true", help="pencere kapanana kadar bekle")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    chrome = find_chrome()
    if chrome is None:
        print("Google Chrome bulunamadı; FDO_CHROME ile chrome.exe yolunu ver.")
        return 1
    profile = profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    url = f"{LOGIN_URL}?.done={quote(FANTASY_URL, safe='')}"
    proc = subprocess.Popen([str(chrome), f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", url])
    print(f"Chrome açıldı (profil: {profile}). Yahoo'ya giriş yap, lig sayfası açılınca pencereyi kapat.")
    if args.wait:
        proc.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
