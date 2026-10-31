"""Lig eşleşme haftalarının tarihleri (README §13.13).

Fantasy haftası pazartesi başlar; 1. hafta sezonun ilk maç günüyle başlar (kısa olabilir).
``config.schedule.merge_with_next`` içindeki haftalar sonrakiyle birleşir (All-Star). Lig ayarındaki
``Playoffs`` metni (ör. ``8 teams - Week 20, 21 and 22 (ends Sunday, Apr 4)``) playoff haftalarını ve son
günü verir; hesaplanan son playoff haftası bu tarihten önce bitiyorsa o hafta son güne kadar uzatılır
(Yahoo'da son playoff turu iki takvim haftası olabilir). Fikstür dosyasında tarih yoktur; tarihler bu
kuralla türetilir ve ekranda gösterilir.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import pandas as pd

from fdo.config import Config

_PLAYOFFS = re.compile(r"Week\s+([\d,\sand]+?)\s*\(ends\s+\w+,\s*([A-Za-z]+)\s+(\d+)\)")


@dataclass(frozen=True)
class LeagueWeeks:
    weeks: pd.DataFrame                          # index week: start, end (date), n_days, playoff
    playoff_weeks: tuple[int, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def week_of(self, day: dt.date) -> int | None:
        hit = self.weeks[(self.weeks["start"] <= day) & (self.weeks["end"] >= day)]
        return int(hit.index[0]) if len(hit) else None

    def days(self, week: int, from_day: dt.date | None = None) -> list[dt.date]:
        start, end = self.weeks.loc[week, "start"], self.weeks.loc[week, "end"]
        if from_day is not None:
            start = max(start, from_day)
        return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def parse_playoffs(text: str, season_start: dt.date) -> tuple[tuple[int, ...], dt.date | None]:
    m = _PLAYOFFS.search(text or "")
    if not m:
        return (), None
    weeks = tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
    month = dt.datetime.strptime(m.group(2)[:3], "%b").month
    year = season_start.year + (1 if month < season_start.month else 0)
    return weeks, dt.date(year, month, int(m.group(3)))


def league_weeks(schedule: pd.DataFrame, settings: dict[str, str], config: Config) -> LeagueWeeks:
    dates = pd.to_datetime(schedule["game_date"]).dt.date
    first, last = dates.min(), dates.max()
    anchor = first - dt.timedelta(days=first.weekday())                 # pazartesi
    n_cal = (last - anchor).days // 7 + 1
    cal = [(max(anchor + dt.timedelta(days=7 * i), first), anchor + dt.timedelta(days=7 * i + 6))
           for i in range(n_cal)]
    merges = {int(m) for m in config.schedule.merge_with_next}
    weeks, i = [], 0
    while i < len(cal):
        start, end = cal[i]
        if len(weeks) + 1 in merges and i + 1 < len(cal):
            end = cal[i + 1][1]
            i += 1
        weeks.append((start, end))
        i += 1
    notes = []
    po, po_end = parse_playoffs(settings.get("Playoffs", ""), first)
    if po and po_end:
        last_po = max(po)
        if last_po <= len(weeks):
            start, end = weeks[last_po - 1]
            if end < po_end:
                weeks[last_po - 1] = (start, po_end)
                notes.append(f"{last_po}. hafta (son playoff) {start:%d.%m}–{po_end:%d.%m} olarak uzatıldı "
                             "(lig ayarındaki bitiş tarihi).")
            elif end > po_end:
                notes.append(f"Hesaplanan {last_po}. hafta {end:%d.%m}'de bitiyor, ayar {po_end:%d.%m} diyor.")
            weeks = weeks[:last_po]
    else:
        notes.append("Playoff ayarı okunamadı; haftalar takvimden türetildi.")
    df = pd.DataFrame(weeks, columns=["start", "end"], index=pd.Index(range(1, len(weeks) + 1), name="week"))
    df["n_days"] = [(e - s).days + 1 for s, e in weeks]
    df["playoff"] = df.index.isin(po)
    return LeagueWeeks(df, tuple(po), tuple(notes))
