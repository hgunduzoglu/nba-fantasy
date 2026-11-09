"""Yahoo senkronizasyonunun içinde bulunulan hafta verisi (``yahoo_live.json``, README §13.20).

Her lig için: Yahoo hafta numarası, takımların haftanın şu ana kadarki toplamları ve kategori skoru, kullanıcının
takımı, bu hafta kullanılan alım hakkı, FAB bütçesi ve waiver'daki oyuncuların serbest kalma tarihleri.
Toplamlar çekildiği ana kadardır; ``live`` işaretliyse o günün kısmi skoru da içindedir.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

FILE = "yahoo_live.json"


def stat(v) -> float:
    """Hafta toplamındaki değer; Yahoo'nun \"-\" gösterdiği (henüz maç yok → NaN) ya da eksik değer 0."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def has_stats(totals: dict | None) -> bool:
    """Toplamlarda en az bir sayı var mı (haftanın ilk maçı oynanmadan Yahoo hepsini \"-\" gösterir)."""
    return any(isinstance(v, (int, float)) and math.isfinite(v) for v in (totals or {}).values())


@dataclass(frozen=True)
class LiveLeague:
    league_id: str
    week: int
    as_of: dt.date
    captured_at: str
    live: bool
    my_team: str | None
    adds_used: int | None = None
    adds_limit: int | None = None
    fab: int | None = None
    totals: dict[str, dict[str, float]] = field(default_factory=dict)     # takım → fgm, fga, …, tov
    category_wins: dict[str, int] = field(default_factory=dict)
    opponents: dict[str, str] = field(default_factory=dict)
    waivers: dict[str, dt.date | None] = field(default_factory=dict)      # oyuncu → serbest kalma günü

    def adds_left(self, team: str, limit: int) -> int | None:
        """Kullanıcının takımı için kalan alım hakkı; başka takım ya da bilinmiyorsa ``None``."""
        if team != self.my_team or self.adds_used is None:
            return None
        return max(0, (self.adds_limit or limit) - self.adds_used)


def load_live(directory: str | Path) -> dict[str, LiveLeague]:
    path = Path(directory) / FILE
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    as_of = dt.date.fromisoformat(doc["as_of"])
    out = {}
    for lid, lg in doc.get("leagues", {}).items():
        totals, wins, opp = {}, {}, {}
        for m in lg.get("matchups", []):
            a, b = str(m["team_a_id"]), str(m["team_b_id"])
            totals[a], totals[b] = m["team_a_totals"], m["team_b_totals"]
            wins[a], wins[b] = m.get("team_a_category_wins"), m.get("team_b_category_wins")
            opp[a], opp[b] = b, a
        waivers = {str(w["player_id"]): dt.date.fromisoformat(w["until"]) if w.get("until") else None
                   for w in lg.get("waivers", [])}
        out[str(lid)] = LiveLeague(str(lid), int(lg["week"]), as_of, doc.get("captured_at", ""), bool(doc.get("live")),
                                   lg.get("my_team"), lg.get("adds_used"), lg.get("adds_limit"), lg.get("fab"),
                                   totals, wins, opp, waivers)
    return out
