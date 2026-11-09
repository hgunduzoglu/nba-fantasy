"""Dış kaynaktaki oyuncu adı (+ NBA takımı) → Yahoo oyuncu kimliği.

İsim benzerliğiyle (bulanık) otomatik birleştirme yapılmaz. Kurallar sırayla denenir; bir kural yalnız **tek** aday
bırakıyorsa eşleşir:

1. ``override``: elle düzeltme (``id_overrides.csv``: ``source, name, nba_team, player_id, note``; ``source`` ve
   ``nba_team`` boşsa her kaynak/takım için geçerli). Kayıt kimin neyi neden düzelttiğini taşır.
2. ``name_team``: ad + NBA takımı (``normalize_name``: küçük harf, aksan, noktalama, Jr./Sr./II/III temizliği).
3. ``name``: yalnız ad, havuzda tek oyuncu. Takım tutmuyorsa ``team_mismatch`` (takım değiştirmiş olabilir; raporlanır).
4. ``initial_team``: baş harf + soyad + takım ("N. Alexander-Walker" = "Nickeil Alexander-Walker", "Nic Claxton" =
   "Nicolas Claxton").

Birden çok aday kalırsa ``ambiguous`` (eşlenmez, karantinada; elle düzeltme gerekir), hiç aday yoksa ``unmatched``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from fdo.ingest.load import normalize_name
from fdo.schedule.calendar import normalize_team

OVERRIDES_FILE = "id_overrides.csv"


def initial_form(n: str) -> str:
    """``"nickeil alexander walker"`` → ``"n alexander walker"`` (Yahoo'nun kısaltılmış adlarıyla eşleşme)."""
    parts = n.split()
    return " ".join([parts[0][0], *parts[1:]]) if len(parts) > 1 else n


def _team(t) -> str:
    return normalize_team(t) if isinstance(t, str) and t.strip() else ""


@dataclass(frozen=True)
class Match:
    player_id: str | None
    status: str                                  # matched | ambiguous | unmatched
    method: str | None = None                    # override | name_team | name | initial_team
    candidates: tuple[str, ...] = ()
    team_mismatch: bool = False


def load_overrides(directory: str | Path | None) -> pd.DataFrame | None:
    if directory is None:
        return None
    path = Path(directory) / OVERRIDES_FILE
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = {"name", "player_id"} - set(df.columns)
    if missing:
        raise ValueError(f"{OVERRIDES_FILE}: eksik sütun {sorted(missing)}")
    return df


class Resolver:
    def __init__(self, players: pd.DataFrame, overrides: pd.DataFrame | None = None, source: str = ""):
        key = pd.DataFrame({"player_id": players.index.astype(str),
                            "n": players["name"].map(normalize_name).to_numpy(),
                            "t": players["nba_team"].map(_team).to_numpy()})
        key["i"] = key["n"].map(initial_form)
        self.team = dict(zip(key["player_id"], key["t"]))
        self.by_both = key.groupby(["n", "t"])["player_id"].agg(tuple).to_dict()
        self.by_name = key.groupby("n")["player_id"].agg(tuple).to_dict()
        self.by_initial = key.groupby(["i", "t"])["player_id"].agg(tuple).to_dict()
        self.overrides: dict[tuple[str, str], str] = {}
        known = set(key["player_id"])
        for r in (overrides.itertuples() if overrides is not None else ()):
            if getattr(r, "source", "") in ("", source) and str(r.player_id) in known:
                self.overrides[(normalize_name(r.name), _team(getattr(r, "nba_team", "")))] = str(r.player_id)

    def __call__(self, name, team: str = "") -> Match:
        n, t = normalize_name(name), _team(team)
        if not n:
            return Match(None, "unmatched")
        hit = self.overrides.get((n, t)) or self.overrides.get((n, ""))
        if hit:
            return Match(hit, "matched", "override")
        ambiguous: tuple[str, ...] = ()
        rules = (("name_team", self.by_both.get((n, t)) if t else None), ("name", self.by_name.get(n)),
                 ("initial_team", self.by_initial.get((initial_form(n), t)) if t else None))
        for method, cands in rules:
            if not cands:
                continue
            if len(cands) == 1:
                pid = cands[0]
                return Match(pid, "matched", method, cands, bool(t and self.team.get(pid) and self.team[pid] != t))
            ambiguous = ambiguous or cands
        return Match(None, "ambiguous", None, ambiguous) if ambiguous else Match(None, "unmatched")

    def player_id(self, name, team: str = "") -> str | None:
        return self(name, team).player_id


@dataclass
class IdentityReport:
    """Bir kaynağın eşleştirme özeti: kaç satır, hangileri eşleşmedi ya da belirsiz kaldı."""

    source: str
    rows: int = 0
    matched: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    team_mismatch: list[str] = field(default_factory=list)

    def add(self, label: str, m: Match) -> None:
        self.rows += 1
        if m.status == "matched":
            self.matched += 1
            self.by_method[m.method] = self.by_method.get(m.method, 0) + 1
            if m.team_mismatch:
                self.team_mismatch.append(label)
        elif m.status == "ambiguous":
            self.ambiguous.append(label)
        else:
            self.unmatched.append(label)

    def note(self, limit: int = 8) -> str:
        def names(xs):
            return ", ".join(xs[:limit]) + (f" ve {len(xs) - limit} diğer" if len(xs) > limit else "")
        parts = [f"{self.source}: {self.rows} satır, {self.matched} eşleşti"]
        if self.unmatched:
            parts.append(f"eşleşmeyen {len(self.unmatched)} satır ({names(self.unmatched)})")
        if self.ambiguous:
            parts.append(f"belirsiz {len(self.ambiguous)} satır, eşlenmedi ({names(self.ambiguous)}; "
                         f"{OVERRIDES_FILE} ile düzeltilebilir)")
        if self.team_mismatch:
            parts.append(f"takımı farklı {len(self.team_mismatch)} ({names(self.team_mismatch)})")
        return "; ".join(parts) + "."
