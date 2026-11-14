"""Menajer profili: ligdeki işlem geçmişinden etkinlik (``transactions.csv``).

Yahoo işlem sayfasının satırları (``raw_text``) ve işlemi yapan takım (``team_ids``) okunur: boştan alım ("Free Agent",
waiver'dan alım), bırakma ("To Waivers"), takas ("Traded to"), veto edilen takas ("Vetoed Trade"). Son işlem tarihi
satırdaki "Oct 31, 4:55 am" biçiminden, yıl çekim zamanından. Profil bir bağlamdır: menajerin teklif kabul eğilimi
ölçülmedi, kabul gerekçesi düzeyini değiştirmez. Dosya senkronizasyonla güncellenmiyorsa eskiyebilir; çekim zamanı
profille birlikte döner.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_WHEN = re.compile(r"\b([A-Z][a-z]{2}) (\d{1,2}), \d{1,2}:\d{2} [ap]m")
_ADD = re.compile(r"(?<!To )(?:Free Agent|Waiver\b)")              # "Free Agent" / "$3 Waiver": alım
_DROP = re.compile(r"To (?:Waivers|Free Agent)")                     # bırakma


@dataclass(frozen=True)
class ManagerProfile:
    team_id: str
    adds: int
    drops: int
    trades: int
    vetoed: int
    last_action: dt.date | None


def _date(text: str, captured: dt.date) -> dt.date | None:
    m = _WHEN.search(text)
    if not m:
        return None
    month = dt.datetime.strptime(m.group(1), "%b").month
    year = captured.year - (1 if month > captured.month else 0)          # Aralık işlemi Ocak'ta çekilmişse
    return dt.date(year, month, int(m.group(2)))


def load_transactions(directory: str | Path) -> pd.DataFrame | None:
    path = Path(directory) / "transactions.csv"
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else None


def profiles(transactions: pd.DataFrame | None, league_id: str, teams) -> tuple[dict[str, ManagerProfile], str | None]:
    """Takım → profil (işlem yoksa sıfırlar) ve dosyanın çekim zamanı (en yenisi; yoksa ``None``)."""
    rows = transactions[transactions["league_id"] == str(league_id)] if transactions is not None else pd.DataFrame()
    captured = str(rows["captured_at"].max()) if len(rows) else None
    day = pd.Timestamp(captured).date() if captured else dt.date.today()
    count = {t: {"adds": 0, "drops": 0, "trades": 0, "vetoed": 0, "last": None} for t in teams}
    for r in rows.itertuples():
        text = str(r.raw_text)
        acting = [t for t in str(r.team_ids).split(",") if t in count]
        when = _date(text, day)
        for t in acting:
            c = count[t]
            if "Vetoed Trade" in text:
                c["vetoed"] += 1
            elif "Traded to" in text:
                c["trades"] += 1
            else:
                c["adds"] += len(_ADD.findall(text))
                c["drops"] += len(_DROP.findall(text))
            if when and (c["last"] is None or when > c["last"]):
                c["last"] = when
    out = {t: ManagerProfile(t, c["adds"], c["drops"], c["trades"], c["vetoed"], c["last"])
           for t, c in count.items()}
    return out, captured
