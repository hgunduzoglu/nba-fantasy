"""Bilgisayardaki güncel veriyi salt okunur sunucuya gönderir (README §14.2).

    python scripts/push_data.py --host <ssh-host>     # ya da FDO_PUSH_HOST ortam değişkeni
    python scripts/push_data.py --dry-run             # yalnızca listele

Önce bilgisayarda ``scripts/yahoo_sync.py`` ve ``scripts/news_refresh.py`` çalışır; bu betik ``data/real`` altında git'in
izlemediği uygulama dosyalarını (kadrolar, skorlar, projeksiyonlar, CBS sakatlık raporu, NBA maç kayıtları, haberler)
tek bir tar.gz olarak ``ssh`` ile gönderir; sunucuda ``scripts/receive_data.py`` yerine koyar. Gönderilmeyen:
``snapshots/``, yönetici iletişim bilgileri, ham yakalamalar ve README notları. Sunucu yeni dosyaları kendisi fark eder
(dosya imzası): yeniden başlatma gerekmez. Kod değiştiyse sunucuda ``git pull``, arayüz derlemesi ve yeniden başlatma.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = "data/real"
SKIP_DIRS = ("snapshots/",)
SKIP_NAMES = frozenset({"managers.csv", "managers.json"})          # iletişim bilgileri; uygulama okumaz
SKIP_SUFFIXES = (".tmp", ".txt", "_capture.json")


def keep(rel: str) -> bool:
    sub = rel[len(DATA) + 1:]
    name = sub.rsplit("/", 1)[-1]
    return bool(sub) and not sub.startswith(SKIP_DIRS) and name not in SKIP_NAMES and not name.endswith(SKIP_SUFFIXES)


def data_files(root: Path = ROOT) -> list[str]:
    """``data/real`` altında git'in izlemediği (ignore edilen) dosyalar, gönderilecek olanlar."""
    out = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z", DATA],
                         cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(f for f in out.split("\0") if f.startswith(DATA + "/") and keep(f) and (root / f).is_file())


def archive(files: list[str], root: Path = ROOT) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in files:
            tar.add(root / f, arcname=f, recursive=False)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("FDO_PUSH_HOST"),
                    help="ssh hedefi (~/.ssh/config takma adı; varsayılan FDO_PUSH_HOST)")
    ap.add_argument("--app", default="/srv/fantasy/app", help="sunucudaki repo dizini")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    files = data_files()
    if not files:
        print("Gönderilecek dosya yok (data/real).", file=sys.stderr)
        return 1
    if not args.host and not args.dry_run:
        print("Sunucu belirtilmedi: --host <ssh-host> ya da FDO_PUSH_HOST", file=sys.stderr)
        return 2
    blob = archive(files)
    print(f"{len(files)} dosya, {len(blob) / 1e6:.1f} MB → {args.host}:{args.app}", flush=True)
    if args.dry_run:
        print("\n".join(files))
        return 0
    remote = f"sudo -u fantasy {args.app}/.venv/bin/python {args.app}/scripts/receive_data.py {args.app}"
    return subprocess.run(["ssh", args.host, remote], input=blob).returncode


if __name__ == "__main__":
    raise SystemExit(main())
