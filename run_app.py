"""Trade Lab web uygulamasını başlatır: React arayüzü + FastAPI (README §15).

    python run_app.py            # http://127.0.0.1:8000 (gerekirse arayüzü önce derler)
    python run_app.py --port 8010 --no-browser
    python run_app.py --rebuild  # arayüzü zorla yeniden derle

Arayüz kaynağı ``frontend/src``; derlenmiş hali ``frontend/dist`` (git'e girmez). Node.js/npm gerekir yalnızca
derleme için. Draft/auction araçları ayrı: ``streamlit run src/fdo/ui/app.py``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"


def needs_build() -> bool:
    index = DIST / "index.html"
    if not index.exists():
        return True
    built = index.stat().st_mtime
    sources = [p for p in (FRONTEND / "src").rglob("*") if p.is_file()]
    sources += [FRONTEND / n for n in ("index.html", "package.json", "vite.config.ts")]
    return any(p.exists() and p.stat().st_mtime > built for p in sources)


def build() -> None:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        sys.exit("npm bulunamadı: arayüzü derlemek için Node.js kurulu olmalı (https://nodejs.org).")
    if not (FRONTEND / "node_modules").exists():
        print("Arayüz bağımlılıkları kuruluyor (bir kerelik)…", flush=True)
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    print("Arayüz derleniyor…", flush=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    if args.rebuild or needs_build():
        build()
    import uvicorn

    from fdo.api.app import create_app

    url = f"http://{args.host}:{args.port}"
    print(f"Trade Lab → {url}  (kapatmak için Ctrl+C)", flush=True)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
