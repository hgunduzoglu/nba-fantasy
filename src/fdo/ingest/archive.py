"""Değiştirilemez ham veri arşivi: analiz girdilerinin içerik adresli kopyaları ve parti (batch) manifestleri.

Yerleşim (``<veri>/snapshots/`` altında, git dışı, sunucuya gönderilmez)::

    objects/<sha256 ilk 2>/<sha256>.gz   dosya içeriği (gzip); aynı içerik yalnız bir kez saklanır
    batches/<batch_id>.json              o anki girdi kümesi: dosya adı → sha256, zaman ve kapsam bilgisi

* **Değişmez**: nesne ve manifestlerin üzerine yazılmaz. Aynı gün ikinci çekim yeni bir parti olur; ilki durur.
* **Tekrarsız**: girdiler son partiyle birebir aynıysa yeni parti açılmaz; aynı dosya ikinci kez saklanmaz.
* **Atomik**: önce nesneler, en son manifest (geçici dosya + ``replace``) yazılır; yarıda kalan arşivleme parti
  oluşturmaz, var olan partileri bozmaz.
* **Geri yükleme**: ``restore`` bir partinin dosyalarını boş bir dizine yazar (ör. aynı analizi yeniden üretmek için);
  her dosyanın özeti doğrulanır.

Zaman alanları ``fdo.ingest.timestamps`` ile dosyanın kendi kaydından okunur; bilinmeyen zaman boş kalır.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from fdo.ingest.timestamps import file_times

SCHEMA_VERSION = "1"
#: Analizin okuduğu dosyalar (``fdo.trade.data.file_signature`` de bunları izler).
ANALYSIS_INPUTS = ("rosters.json", "league_info.json", "player_stat_pages.json", "matchups.json", "yahoo_live.json",
                   "standings*.csv", "players_yahoo_*.csv", "projections_yahoo_*.csv", "variance*.csv", "schedule*.csv",
                   "injuries*.csv", "gamelogs_nba_*.csv", "adp_yahoo_*.csv", "draft_results.csv", "fixtures*.csv")
#: Analizin doğrudan okumadığı ama geriye dönük inceleme için saklanan dosyalar.
ARCHIVE_EXTRA = ("news.json", "transactions.csv")
#: Bunlar olmadan analiz kurulamaz; partide yoksa ``missing`` ve ``complete=False``.
REQUIRED = ("rosters.json", "league_info.json", "player_stat_pages.json", "players_yahoo_*.csv",
            "projections_yahoo_*.csv", "schedule*.csv")


def _glob(directory: Path, patterns) -> list[Path]:
    found = {p for pat in patterns for p in directory.glob(pat) if p.is_file() and not p.name.endswith(".tmp")}
    return sorted(found)


def input_files(directory: str | Path) -> list[Path]:
    return _glob(Path(directory), ANALYSIS_INPUTS)


def archive_files(directory: str | Path) -> list[Path]:
    return _glob(Path(directory), ANALYSIS_INPUTS + ARCHIVE_EXTRA)


def root(directory: str | Path) -> Path:
    return Path(directory) / "snapshots"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _object(directory: Path, digest: str) -> Path:
    return root(directory) / "objects" / digest[:2] / f"{digest}.gz"


def _store(directory: Path, digest: str, path: Path) -> bool:
    target = _object(directory, digest)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    with open(path, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    tmp.replace(target)
    return True


@dataclass(frozen=True)
class ArchiveResult:
    batch_id: str
    created: bool                     # False: girdiler son partiyle aynıydı
    new_objects: int
    files: int


def batches(directory: str | Path) -> list[dict]:
    """Partilerin manifestleri, eskiden yeniye (sıra numarası; aynı saniyede açılan partiler de sıralı)."""
    d = root(directory) / "batches"
    out = [json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.json")] if d.exists() else []
    return sorted(out, key=lambda m: (m["sequence"], m["ingested_at"]))


def latest(directory: str | Path) -> dict | None:
    """Son parti. Parti adları giriş zamanıyla başladığından yalnız en yeni saniyedeki manifestler okunur."""
    d = root(directory) / "batches"
    names = sorted(p.name for p in d.glob("*.json")) if d.exists() else []
    if not names:
        return None
    prefix = names[-1].split("-")[0]
    tail = [json.loads((d / n).read_text(encoding="utf-8")) for n in names if n.startswith(prefix)]
    return max(tail, key=lambda m: m["sequence"])


def get(directory: str | Path, batch_id: str) -> dict:
    path = root(directory) / "batches" / f"{batch_id}.json"
    if not path.exists():
        raise KeyError(f"Arşivde böyle bir parti yok: {batch_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _missing(names: set[str]) -> list[str]:
    return [pat for pat in REQUIRED if not any(Path(n).match(pat) for n in names)]


def archive(directory: str | Path, *, source: str, note: str = "", files: list[Path] | None = None,
            now: dt.datetime | None = None) -> ArchiveResult:
    """``directory``'deki arşiv dosyalarını (ya da verilen ``files``) yeni bir parti olarak saklar.

    ``source``: partiyi kim oluşturdu (``yahoo_sync``, ``manual``, ``legacy:<gün>``...). Girdiler son partiyle aynıysa
    yeni parti açılmaz (``created=False``)."""
    directory = Path(directory)
    paths = sorted(files) if files is not None else archive_files(directory)
    names = [p.name for p in paths]
    if len(names) != len(set(names)):
        raise ValueError("Bir partide aynı adlı iki dosya olamaz")
    digests = {p.name: sha256(p) for p in paths}
    last = latest(directory)
    if last and {n: f["sha256"] for n, f in last["files"].items()} == digests:
        return ArchiveResult(last["batch_id"], False, 0, len(digests))
    new = sum(_store(directory, digests[p.name], p) for p in paths)
    ingested = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    content = hashlib.sha256("|".join(f"{n}:{digests[n]}" for n in sorted(digests)).encode()).hexdigest()
    batch_id = f"{ingested:%Y%m%dT%H%M%SZ}-{content[:8]}"
    missing = _missing(set(names))
    manifest = {
        "schema_version": SCHEMA_VERSION, "batch_id": batch_id, "sequence": last["sequence"] + 1 if last else 1,
        "source": source, "note": note,
        "ingested_at": ingested.isoformat(timespec="seconds"), "timezone": "UTC",
        "previous_batch_id": last["batch_id"] if last else None,
        "complete": not missing, "missing": missing, "content_hash": content,
        "files": {p.name: {"sha256": digests[p.name], "bytes": p.stat().st_size, **file_times(p)} for p in paths},
    }
    target = root(directory) / "batches" / f"{batch_id}.json"
    if target.exists():                           # aynı saniyede aynı içerik: zaten saklı
        return ArchiveResult(batch_id, False, new, len(digests))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)
    return ArchiveResult(batch_id, True, new, len(digests))


def restore(directory: str | Path, batch_id: str, dest: str | Path) -> list[Path]:
    """Partinin dosyalarını ``dest`` dizinine yazar (dizin boş olmalı); her dosyanın sha256'sı doğrulanır."""
    manifest = get(directory, batch_id)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise ValueError(f"Hedef dizin boş değil: {dest}")
    out = []
    for name, info in sorted(manifest["files"].items()):
        target = dest / name
        with gzip.open(_object(Path(directory), info["sha256"]), "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if sha256(target) != info["sha256"]:
            raise ValueError(f"Arşiv nesnesi bozuk: {name} ({batch_id})")
        out.append(target)
    return out


def verify(directory: str | Path, batch_id: str | None = None) -> list[str]:
    """Partilerin (ya da birinin) nesneleri yerinde ve özetleri doğru mu; sorunların listesi (boş = sağlam)."""
    problems = []
    for m in ([get(directory, batch_id)] if batch_id else batches(directory)):
        for name, info in m["files"].items():
            obj = _object(Path(directory), info["sha256"])
            if not obj.exists():
                problems.append(f"{m['batch_id']}: {name} nesnesi yok")
                continue
            h = hashlib.sha256()
            with gzip.open(obj, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != info["sha256"]:
                problems.append(f"{m['batch_id']}: {name} özeti tutmuyor")
    return problems
