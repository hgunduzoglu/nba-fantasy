"""Karar günlüğü: sistemin ürettiği önerilerin ve incelenen senaryoların yalnız-ekleme kaydı.

Geriye dönük değerlendirme için her kayıt, o anda bilinenleri taşır: veri imzası ve tarihi, arşivdeki son parti
(``fdo.ingest.archive``), kod sürümü, istek ve sonucun özeti. Kayıt türleri ayrıdır:

* ``recommendation``: sistemin önerdiği işlemler (takas önerileri, tamamlama).
* ``scenario``: kullanıcının ekranda incelediği varsayımsal takas; gerçek kadroyu değiştirmez.
* ``user_reported``: kullanıcının "yaptım" dediği işlem. Son doğrulanmış veriyi değiştirmez; sonraki içe aktarmayla
  uzlaştırılacak bir olay olarak durur.

Dosya ``<veri>/decisions/<YYYY-MM>.jsonl`` (git dışı); satırlar yalnız sona eklenir. ``FDO_DECISION_LOG=0`` kapatır.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid
from pathlib import Path

KINDS = ("recommendation", "scenario", "user_reported")


class DecisionLog:
    def __init__(self, directory: str | Path, *, enabled: bool | None = None, code: dict | None = None):
        self.dir = Path(directory) / "decisions"
        self.enabled = os.environ.get("FDO_DECISION_LOG", "1") != "0" if enabled is None else enabled
        self._code = code
        self._lock = threading.Lock()

    def code(self) -> dict:
        if self._code is None:
            from fdo.evaluation.cases import code_version
            self._code = code_version()
        return self._code

    def record(self, kind: str, action: str, league_id: str, request: dict, result: dict, *,
               data_signature: str, data_as_of: str, batch_id: str | None = None,
               now: dt.datetime | None = None) -> str | None:
        """Kaydı ekler ve kimliğini döner (kapalıysa ``None``). Yazma hatası analizi durdurmaz."""
        if kind not in KINDS:
            raise ValueError(f"Bilinmeyen kayıt türü: {kind}")
        if not self.enabled:
            return None
        now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
        entry = {"decision_id": uuid.uuid4().hex, "created_at": now.isoformat(timespec="seconds"), "kind": kind,
                 "action": action, "league_id": str(league_id), "data_signature": data_signature,
                 "data_as_of": data_as_of, "batch_id": batch_id, "code": self.code(), "request": request,
                 "result": result}
        line = json.dumps(entry, ensure_ascii=False, default=str)
        try:
            with self._lock:
                self.dir.mkdir(parents=True, exist_ok=True)
                with open(self.dir / f"{now:%Y-%m}.jsonl", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            return None
        return entry["decision_id"]

    def entries(self, kind: str | None = None) -> list[dict]:
        out = []
        for path in sorted(self.dir.glob("*.jsonl")) if self.dir.exists() else []:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    e = json.loads(line)
                    if kind is None or e["kind"] == kind:
                        out.append(e)
        return out
