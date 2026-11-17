"""Senaryo katmanı: bekleyen ya da varsayımsal takaslar ve rol çarpanları (README §13.53).

Senaryo istemcide durur (sunucu salt okunur) ve her istekle ``X-FDO-Scenario`` başlığında gelir; ``AppState`` veriyi
yüklerken uygular, böylece bütün sayfalar (takas, öneri, bu hafta, sezon) aynı varsayımla çalışır.

* **Takas adımları** sırayla, motorun kendi kadro çözümüyle (``TradeEngine.resolve``) uygulanır: IL'e alma, bırakma ve
  (istenirse) boştan doldurma takas analiziyle aynıdır; bir adımın sonucu sonrakinin başlangıcıdır (zincirleme takas).
  Adımdaki oyuncu artık o takımda değilse (takas Yahoo'da işlenmiş, ya da oyuncu el değiştirmiş) adım atlanır ve
  nedeni bildirilir; senaryo kayıtlı bir kadro anlık görüntüsü değil, güncel veriye uygulanan farktır.
* **Rol çarpanı** oyuncunun kalan sezon satırındaki sayım istatistiklerini (maç sayısı ve yüzdeler değişmez) her
  değerlendirme temelinde çarpar. Bu sezonun ve sezon öncesinin kaynakları dokunulmaz: rakibin algıladığı değer
  kullanıcının beklentisiyle değişmez.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from fdo.trade.data import ROS, TradeData
from fdo.trade.engine import TradeEngine, TradeError, TradeRequest
from fdo.types import STATS

HEADER = "x-fdo-scenario"
ROLE_RANGE = (.25, 3.0)
MAX_STEPS = 12


@dataclass(frozen=True)
class Step:
    league: str
    team_a: str
    team_b: str
    give_a: tuple[str, ...]
    give_b: tuple[str, ...]
    drop_a: tuple[str, ...] = ()
    drop_b: tuple[str, ...] = ()
    add_a: tuple[str, ...] = ()
    add_b: tuple[str, ...] = ()
    auto: bool = True

    def request(self) -> TradeRequest:
        return TradeRequest(self.team_a, self.team_b, self.give_a, self.give_b, self.drop_a, self.drop_b,
                            self.add_a, self.add_b, self.auto, self.auto)


@dataclass(frozen=True)
class Overlay:
    steps: tuple[Step, ...] = ()
    roles: tuple[tuple[str, float], ...] = ()         # (oyuncu, çarpan), kimliğe göre sıralı

    @property
    def empty(self) -> bool:
        return not self.steps and not self.roles

    def trades_key(self) -> str:
        return _digest([dataclasses.asdict(s) for s in self.steps])

    def roles_key(self) -> str:
        return _digest(self.roles)

    @classmethod
    def parse(cls, obj) -> "Overlay":
        """İstemci biçimi: ``{"trades": [{"league", "team_a", "team_b", "give_a", "give_b", "drop_a"?, ..., "auto"?}],
        "roles": {"oyuncu": çarpan}}``. Biçim bozuksa ``ValueError``."""
        if obj is None:
            return cls()
        if not isinstance(obj, dict):
            raise ValueError("Senaryo bir nesne olmalı")
        trades, roles = obj.get("trades") or [], obj.get("roles") or {}
        if not isinstance(trades, list) or not isinstance(roles, dict) or len(trades) > MAX_STEPS:
            raise ValueError(f"Senaryo: takas listesi (en çok {MAX_STEPS}) ve rol sözlüğü bekleniyor")
        steps = []
        for t in trades:
            if not isinstance(t, dict):
                raise ValueError("Senaryo takası bir nesne olmalı")
            ids = {k: tuple(str(x) for x in (t.get(k) or ())) for k in
                   ("give_a", "give_b", "drop_a", "drop_b", "add_a", "add_b")}
            try:
                steps.append(Step(str(t["league"]), str(t["team_a"]), str(t["team_b"]), auto=bool(t.get("auto", True)),
                                  **ids))
            except KeyError as e:
                raise ValueError(f"Senaryo takasında eksik alan: {e.args[0]}") from e
        out = []
        for pid, f in roles.items():
            try:
                f = float(f)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Rol çarpanı sayı olmalı: {pid}") from e
            if not ROLE_RANGE[0] <= f <= ROLE_RANGE[1]:
                raise ValueError(f"Rol çarpanı {ROLE_RANGE[0]}–{ROLE_RANGE[1]} aralığında olmalı: {pid}")
            if f != 1.0:
                out.append((str(pid), f))
        return cls(tuple(steps), tuple(sorted(out)))


def _digest(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:12]


#: Bu isteğin senaryosu (ara katman ayarlar; arka plan işleri ve senaryosuz istekler için ``None``).
CURRENT: ContextVar[Overlay | None] = ContextVar("fdo_overlay", default=None)


def current() -> Overlay | None:
    ov = CURRENT.get()
    return None if ov is None or ov.empty else ov


@contextmanager
def suspended():
    """Bu blokta senaryo yok sayılır (ör. gerçek durumla karşılaştırma)."""
    token = CURRENT.set(None)
    try:
        yield
    finally:
        CURRENT.reset(token)


def apply_trades(data: TradeData, overlay: Overlay) -> tuple[TradeData, list[dict]]:
    """Takas adımlarını sırayla uygular; ``(yeni veri, adım durumları)``. Durum: ``applied`` (kadro değişiklikleri),
    ``skipped`` (oyuncu artık o takımda değil) ya da ``error`` (geçersiz takas, ör. alım hakkı yok)."""
    status: list[dict] = []
    name = data.players["name"]
    for k, step in enumerate(overlay.steps):
        lg = data.leagues.get(step.league)
        row = {"index": k, "league": step.league}
        if lg is None or step.team_a not in lg.rosters or step.team_b not in lg.rosters:
            status.append({**row, "status": "error", "reason": "Lig ya da takım yok"})
            continue
        gone = [p for t, give in ((step.team_a, step.give_a), (step.team_b, step.give_b))
                for p in give if p not in lg.rosters[t]]
        if gone:
            where = {p: next((lg.teams[t] for t, r in lg.rosters.items() if p in r), "boşta") for p in gone}
            status.append({**row, "status": "skipped",
                           "reason": "Artık o takımda değil: " + ", ".join(f"{name.get(p, p)} ({w})"
                                                                         for p, w in where.items())
                                     + " — takas Yahoo'da işlenmiş olabilir"})
            continue
        try:
            eng = TradeEngine(data, step.league, free_moves=False)
            rosters, adjustments, il = eng.resolve(step.request())
        except (TradeError, ValueError) as e:
            status.append({**row, "status": "error", "reason": str(e)})
            continue
        changed = {t for t in lg.rosters if set(rosters[t]) != set(lg.rosters[t])
                   or frozenset(il.get(t, ())) != lg.injury_rosters.get(t, frozenset())}
        new = dataclasses.replace(lg, rosters={t: tuple(rosters[t]) for t in lg.rosters},
                                  injury_rosters={t: frozenset(il.get(t, lg.injury_rosters.get(t, ()))) for t in lg.rosters},
                                  lineups={t: v for t, v in lg.lineups.items() if t not in changed})
        data = dataclasses.replace(data, leagues={**data.leagues, step.league: new})
        moves = {t: {kind: [str(name.get(p, p)) for p in ids] for kind, ids in adj.items() if ids}
                 for t, adj in adjustments.items()}
        status.append({**row, "status": "applied", "moves": {lg.teams[t]: m for t, m in moves.items() if m}})
    if overlay.steps:
        data = dataclasses.replace(data, fingerprint=f"{data.fingerprint}:ov{overlay.trades_key()}")
    return data, status


def apply_roles(data: TradeData, overlay: Overlay) -> TradeData:
    """Rol çarpanları: kalan sezon satırının sayım istatistikleri × çarpan (yalnız ``ROS`` kaynağı)."""
    if not overlay.roles:
        return data
    ros = data.stats[ROS].copy()
    for pid, f in overlay.roles:
        if pid in ros.index:
            ros.loc[pid, list(STATS)] = ros.loc[pid, list(STATS)] * f
    return dataclasses.replace(data, stats={**data.stats, ROS: ros},
                               fingerprint=f"{data.fingerprint}:rl{overlay.roles_key()}")


def role_notes(data: TradeData, overlay: Overlay, modeled) -> list[dict]:
    """Rol çarpanı uyarıları: bilinmeyen ya da modellenmeyen oyuncuda çarpan etkisizdir."""
    out = []
    for pid, f in overlay.roles:
        if pid not in data.players.index:
            out.append({"player_id": pid, "factor": f, "status": "error", "reason": "Bilinmeyen oyuncu"})
        elif not modeled(pid):
            out.append({"player_id": pid, "name": data.players.loc[pid, "name"], "factor": f, "status": "error",
                        "reason": "Kalan sezon projeksiyonu yok; çarpan etkisiz"})
        else:
            out.append({"player_id": pid, "name": data.players.loc[pid, "name"], "factor": f, "status": "applied"})
    return out
