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


#: Bu kadar gündür işlem yapmayan menajer sezon simülasyonunda waiver hamlesi yapmaz sayılır (varsayım).
INACTIVE_DAYS = 21


def waiver_order(standings: pd.DataFrame | None, transactions: pd.DataFrame | None, league_id: str, teams,
                 as_of: dt.date, inactive_days: int = INACTIVE_DAYS) -> tuple[str, ...]:
    """Sezon simülasyonunda bedava waiver hamlesi yapan takımlar, ligin waiver önceliğine göre (``standings_live.csv``
    ``waiver_priority``; yoksa sıralama, o da yoksa takım sırası). İşlem geçmişi biliniyorsa son ``inactive_days``
    günde işlem yapmayan takım dışarıda kalır."""
    teams = [str(t) for t in teams]
    order = list(teams)
    if standings is not None and len(standings) and "waiver_priority" in standings:
        sub = standings[standings["league_id"].astype(str) == str(league_id)].copy()
        sub["team_id"] = sub["team_id"].astype(str)
        key = pd.to_numeric(sub["waiver_priority"], errors="coerce").fillna(
            pd.to_numeric(sub.get("rank"), errors="coerce") + 100 if "rank" in sub else 999)
        ranked = list(sub.assign(_k=key).sort_values("_k")["team_id"])
        order = [t for t in ranked if t in teams] + [t for t in teams if t not in ranked]
    prof, captured = profiles(transactions, league_id, teams)
    if captured is None:
        return tuple(order)
    return tuple(t for t in order if prof[t].last_action and (as_of - prof[t].last_action).days <= inactive_days)
