"""Yahoo draft sonuçlarını ``DraftLog``'a birleştirme (README §13.7).

Kurallar:
* **Sıra:** API pick'leri numara sırasıyla eklenir; boş (henüz yapılmamış) pick'te durulur.
  Boştan sonra dolu pick varsa **boşluk** raporlanır ve boşluktan sonrası eklenmez.
* **Koltuk:** pick numarasının koltuğu config'in snake sırasından türetilir. Aynı ``team_key``
  iki farklı koltukta görünürse draft sırası config'le uyuşmuyordur → hata (ekleme yapılmaz).
* **Tekrar (dedupe):** log'da aynı pick'te aynı oyuncu varsa atlanır.
* **Çakışma:** log'da aynı pick'te başka oyuncu varsa: log'daki pick ``manual`` kaynaklıysa
  **elle girilen kazanır** (çakışma raporlanır, API sonrası eklenmez); değilse log o pick'ten
  kesilir ve API'den yeniden kurulur.
* Veri setinde olmayan oyuncu → hata; o pick'te durulur (manuel giriş gerekir).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fdo.draft.events import DraftError, DraftLog
from fdo.yahoo_api.client import DraftResult, player_id_from_key


@dataclass
class SyncReport:
    added: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)          # zaten log'da (dedupe)
    replaced_from: int | None = None                          # log bu pick'ten kesildi
    conflicts: list[tuple[int, str, str]] = field(default_factory=list)   # (pick, log, api)
    gaps: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    team_seats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        parts = [f"{len(self.added)} yeni pick", f"{len(self.skipped)} zaten vardı"]
        if self.replaced_from:
            parts.append(f"log {self.replaced_from}. pick'ten API ile yeniden kuruldu")
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} çakışma (elle girilen korundu)")
        if self.gaps:
            parts.append(f"boşluk: {self.gaps}")
        if self.errors:
            parts.append(f"{len(self.errors)} hata")
        return ", ".join(parts)


def team_seat_map(results: list[DraftResult], log: DraftLog, report: SyncReport) -> dict[str, int]:
    seats: dict[str, int] = {}
    for r in results:
        if not r.team_key or r.pick > log.total_picks:
            continue
        seat = log.seat_for(r.pick)
        if seats.setdefault(r.team_key, seat) != seat:
            report.errors.append(f"{r.team_key} hem seat {seats[r.team_key]} hem seat {seat} pick'inde: "
                                 "draft sırası config'le uyuşmuyor (teams / 3RR / snake?)")
    return seats


def merge(log: DraftLog, results: list[DraftResult], known_players: set[str]) -> tuple[DraftLog, SyncReport]:
    rep = SyncReport()
    rep.team_seats = team_seat_map(results, log, rep)
    if not rep.ok:
        return log, rep
    by_pick = {r.pick: r for r in results}
    filled = sorted(p for p, r in by_pick.items() if r.player_key)
    last = filled[-1] if filled else 0
    for k in range(1, last + 1):
        if k not in by_pick or not by_pick[k].player_key:
            rep.gaps.append(k)
    stop = min(rep.gaps) - 1 if rep.gaps else last

    existing = {p.overall_pick: p for p in log.picks}
    for k in range(1, stop + 1):
        pid = player_id_from_key(by_pick[k].player_key)
        cur = existing.get(k)
        if cur is None:
            break
        if cur.player_id == pid:
            continue
        if cur.source.startswith("manual"):
            rep.conflicts.append((k, cur.player_id, pid))
            return log, rep
        log = log.truncate(k - 1)
        rep.replaced_from = k
        break

    for k in range(1, stop + 1):
        if k <= len(log):
            if k not in rep.added:
                rep.skipped.append(k)
            continue
        pid = player_id_from_key(by_pick[k].player_key)
        if pid not in known_players:
            rep.errors.append(f"Pick {k}: {by_pick[k].player_key} ({pid}) veri setinde yok — elle girin")
            break
        try:
            log = log.make_pick(pid, "import:yahoo_api")
        except DraftError as e:
            rep.errors.append(f"Pick {k}: {e}")
            break
        rep.added.append(k)
    return log, rep
