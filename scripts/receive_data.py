"""Sunucu tarafı: ``scripts/push_data.py``'nin gönderdiği tar.gz'yi (stdin) ``data/real`` altına yazar (README §14.2).

    ... | python scripts/receive_data.py /srv/fantasy/app

Yalnızca ``data/real/`` altındaki düz dosyalar kabul edilir (mutlak yol, ``..`` ve bağlantı reddedilir). Her dosya önce
geçici dizine açılır, sonra ``os.replace`` ile yerine konur: çalışan uygulama yarım dosya görmez. Değiştirilme zamanları
korunur; değişmeyen dosya uygulamanın veri imzasını değiştirmez.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

PREFIX = ("data", "real")


def check(members: list[tarfile.TarInfo]) -> list[tarfile.TarInfo]:
    for m in members:
        p = PurePosixPath(m.name)
        if (not m.isfile() or p.is_absolute() or ".." in p.parts or p.parts[:2] != PREFIX or len(p.parts) < 3):
            raise ValueError(f"Kabul edilmeyen dosya: {m.name}")
    return members


def receive(blob: bytes, root: Path) -> list[str]:
    root = Path(root)
    (root / "data" / "real").mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = check(tar.getmembers())
        tmp = Path(tempfile.mkdtemp(prefix=".incoming-", dir=root / "data"))
        try:
            tar.extractall(tmp, members=members, filter="data")
            for m in members:
                dst = root / m.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp / m.name, dst)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return [m.name for m in members]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    try:
        names = receive(sys.stdin.buffer.read(), root)
    except (ValueError, tarfile.TarError) as e:
        print(f"Sunucu: veri alınamadı, dosyalara dokunulmadı: {e}", file=sys.stderr)
        return 1
    print(f"Sunucu: {len(names)} dosya yazıldı. Yeniden başlatma gerekmez; uygulama yeni veriyi kendisi yükler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
