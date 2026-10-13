"""NBA takvimi → fantasy haftaları ve takım başına maç sayısı (README §13.4).

* Fantasy haftası ``config.schedule.week_start`` gününde başlar; 1. hafta sezonun ilk maçının
  bulunduğu haftadır (kısa olabilir). ``merge_with_next`` içindeki hafta, sonrakiyle tek
  eşleşme sayılır.
* Son ``unverified.playoff_weeks`` eşleşme haftası fantasy playoff'udur (``null`` → yok).
* Oyuncunun haftalık beklenen maç sayısı, takımının eşleşme haftalarındaki maç sayısının
  ``playoff_weight`` ağırlıklı ortalamasıdır (sabit ``games_per_week`` yerine).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fdo.config import Config

#: Kaynaklarda görülen alternatif takım kodları → Yahoo/NBA üç harfli kodu.
TEAM_ALIASES: dict[str, str] = {
    "GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "NOR": "NOP", "UTAH": "UTA", "UTH": "UTA",
    "WSH": "WAS", "PHO": "PHX", "BRK": "BKN", "BRO": "BKN", "NJ": "BKN", "CHO": "CHA", "CHH": "CHA",
}

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def normalize_team(code) -> str:
    c = str(code).strip().upper()
    return TEAM_ALIASES.get(c, c)


def assign_weeks(dates: pd.Series, config: Config) -> pd.Series:
    """Tarih → eşleşme haftası (1-tabanlı), birleştirmeler uygulanmış."""
    d = pd.to_datetime(dates).dt.normalize()
    start = d.min()
    ws = WEEKDAYS.index(config.schedule.week_start)
    anchor = start - pd.Timedelta(days=(start.weekday() - ws) % 7)
    raw = ((d - anchor).dt.days // 7 + 1).astype(int)
    merges = sorted(int(m) for m in config.schedule.merge_with_next)
    return raw.map(lambda w: w - sum(1 for m in merges if m < w)).astype(int)


@dataclass(frozen=True)
class SeasonCalendar:
    days: pd.DataFrame            # game_date, week, team (takım-maç satırları)
    weeks: pd.DataFrame           # index week: start, end, n_days, playoff
    team_week: pd.DataFrame       # takım × hafta maç sayısı

    @property
    def teams(self) -> list[str]:
        return list(self.team_week.index)

    def weights(self, config: Config) -> pd.Series:
        w = pd.Series(1.0, index=self.weeks.index)
        w[self.weeks["playoff"]] = config.model.matchup.playoff_weight
        return w

    def games_mean(self, config: Config) -> pd.Series:
        """Takım → ağırlıklı ortalama eşleşme başına maç."""
        w = self.weights(config)
        return (self.team_week * w).sum(axis=1) / w.sum()

    def games_var(self, config: Config) -> pd.Series:
        """Takım → eşleşmeden eşleşmeye maç sayısı varyansı (ağırlıklı)."""
        w = self.weights(config)
        m = self.games_mean(config)
        return ((self.team_week.sub(m, axis=0) ** 2) * w).sum(axis=1) / w.sum()

    def playing(self, week: int) -> tuple[list[pd.Timestamp], dict[str, set[pd.Timestamp]]]:
        """Haftanın günleri ve takım → oynadığı günler."""
        wk = self.weeks.loc[week]
        days = list(pd.date_range(wk["start"], wk["end"], freq="D"))
        sub = self.days[self.days["week"] == week]
        return days, {t: set(g["game_date"]) for t, g in sub.groupby("team")}


def build_calendar(schedule: pd.DataFrame, config: Config) -> SeasonCalendar:
    s = schedule.copy()
    s["game_date"] = pd.to_datetime(s["game_date"]).dt.normalize()
    long = pd.concat([
        pd.DataFrame({"game_date": s["game_date"], "team": s["home_team"].map(normalize_team)}),
        pd.DataFrame({"game_date": s["game_date"], "team": s["away_team"].map(normalize_team)}),
    ], ignore_index=True)
    long["week"] = assign_weeks(long["game_date"], config)
    g = long.groupby("week")["game_date"]
    weeks = pd.DataFrame({"start": g.min(), "end": g.max()})
    # hafta sınırları: başlangıç gününe hizalı tam hafta (birleşik haftalar uzun)
    ws = WEEKDAYS.index(config.schedule.week_start)
    weeks["start"] = weeks["start"] - pd.to_timedelta((weeks["start"].dt.weekday - ws) % 7, unit="D")
    weeks.loc[weeks.index.min(), "start"] = long["game_date"].min()
    weeks["end"] = weeks["end"] + pd.to_timedelta((ws - 1 - weeks["end"].dt.weekday) % 7, unit="D")
    weeks.loc[weeks.index.max(), "end"] = long["game_date"].max()
    weeks["n_days"] = (weeks["end"] - weeks["start"]).dt.days + 1
    n_po = config.unverified.playoff_weeks or 0
    weeks["playoff"] = weeks.index > weeks.index.max() - n_po
    team_week = long.groupby(["team", "week"]).size().unstack(fill_value=0).reindex(
        columns=weeks.index, fill_value=0)
    return SeasonCalendar(days=long, weeks=weeks, team_week=team_week)


def player_games(players: pd.DataFrame, cal: SeasonCalendar, config: Config
                 ) -> tuple[pd.Series, pd.Series, list[str]]:
    """Oyuncu (``player_id``) → (eşleşme başına beklenen takım maçı, varyansı, bilinmeyen takımlar).

    Takımı takvimde olmayan oyuncu sabit ``games_per_week`` (varyans 0) alır.
    """
    mp = config.model.matchup
    team = players.set_index("player_id")["nba_team"].map(
        lambda t: normalize_team(t) if isinstance(t, str) else "")
    mean = team.map(cal.games_mean(config))
    var = team.map(cal.games_var(config))
    unknown = sorted(set(team[mean.isna()]) - {""})
    return mean.fillna(mp.games_per_week).astype(float), var.fillna(0.0).astype(float), unknown


def week_summary(cal: SeasonCalendar) -> pd.DataFrame:
    """Hafta başına gün sayısı, maç sayısı ve takım başına min/ortalama/maks maç."""
    tw = cal.team_week
    out = cal.weeks[["start", "end", "n_days", "playoff"]].copy()
    out["games"] = (tw.sum(axis=0) / 2).astype(int)
    out["team_min"] = tw.min(axis=0)
    out["team_mean"] = tw.mean(axis=0).round(2)
    out["team_max"] = tw.max(axis=0)
    return out


def season_dates(cal: SeasonCalendar) -> tuple[pd.Timestamp, pd.Timestamp]:
    d = cal.days["game_date"]
    return d.min(), d.max()


__all__ = ["SeasonCalendar", "TEAM_ALIASES", "assign_weeks", "build_calendar", "normalize_team",
           "player_games", "season_dates", "week_summary"]
