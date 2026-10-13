"""Sakatlık ve rol belirsizliği senaryoları (README §13.5, V2).

Her simülasyon ``s`` ve oyuncu ``i`` için haftalık vektör çarpanı ``m_si = (a_si / ā_i) · r_si``:

* **Maç oranı** ``a ~ Beta(ā·κ, (1−ā)·κ)``, ``ā = min(gp, 82)/82`` (projeksiyonun beklenen maç
  oranı); κ küçüldükçe sezon boyu sakatlık/rotasyon riski büyür.
* **Rol** ``r = exp(σ_r·z − σ_r²/2)`` (ortalaması 1): dakika/kullanım değişimi tüm statları
  orantılı ölçekler.

Rookie'ler (``players.is_rookie``) için κ daha küçük, σ_r daha büyüktür. Çarpanların beklentisi
1'dir: E[W] yalnızca doğrusal olmayan ECW yüzünden az değişir; asıl etki P10–P90 yayılımıdır.
Haftalık vektörün tüm bileşenleri (ortalama, varyans, oran bileşenleri) maç sayısı ve role
doğrusal ölçeklendiği için çarpan vektörün tamamına uygulanır.

Çarpanlar simülasyon kimliğiyle tohumlanır (``SeedSequence(seed, spawn_key=(s, 7_777))``):
aynı simülasyon tüm aday çiftlerde aynı senaryoyu görür (CRN), ``sim_offset`` korunur.
"""

from __future__ import annotations

import numpy as np

from fdo.advisor.simulate import AdvisorContext

SCENARIO_KEY = 7_777


def player_params(ctx: AdvisorContext) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Evren sırasıyla ``(ā, κ, σ_r)``; projeksiyonsuz oyuncu ā = 1 (çarpan uygulanmaz)."""
    sp = ctx.config.model.scenarios
    u = ctx.universe
    gp = ctx.dataset.projections.set_index("player_id")["projected_gp"].reindex(u.ids).to_numpy(float)
    cap = ctx.config.model.matchup.games_cap
    abar = np.clip(np.nan_to_num(np.minimum(gp, cap) / cap, nan=1.0), 0.05, 0.98)
    rookie = np.zeros(u.n, dtype=bool)
    if "is_rookie" in ctx.dataset.players:
        flags = ctx.dataset.players.set_index("player_id")["is_rookie"].reindex(u.ids)
        rookie = flags.fillna(False).astype(bool).to_numpy()
    kappa = np.where(rookie, sp.rookie_gp_kappa, sp.gp_kappa)
    role = np.where(rookie, sp.rookie_role_sd, sp.role_sd)
    return abar, kappa, role


def multipliers(ctx: AdvisorContext, sim_ids, seed: int) -> np.ndarray:
    """``(S, n)`` çarpanlar; projeksiyonsuz oyuncular için 1."""
    abar, kappa, role = player_params(ctx)
    out = np.ones((len(sim_ids), ctx.universe.n))
    has = ctx.has_vec
    for row, s in enumerate(sim_ids):
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(int(s), SCENARIO_KEY))))
        a = rng.beta(abar * kappa, (1 - abar) * kappa)
        r = np.exp(role * rng.standard_normal(len(abar)) - role ** 2 / 2)
        out[row] = np.where(has, a / abar * r, 1.0)
    return out


def roster_correction(vecs: np.ndarray, mult: np.ndarray, players) -> np.ndarray:
    """``Σ_i (m_si − 1)·v_i`` — sabit kadroya (``players``) senaryo düzeltmesi ``(S, 24)``."""
    idx = np.asarray(list(players), dtype=np.int64)
    if len(idx) == 0:
        return np.zeros((mult.shape[0], vecs.shape[1]))
    v = np.nan_to_num(vecs[idx])
    return (mult[:, idx] - 1.0) @ v


def choice_correction(vecs: np.ndarray, mult: np.ndarray, choices: list[tuple[int, ...]]) -> np.ndarray:
    """Simülasyona özgü seçimler (π) için ``Σ (m_si − 1)·v_i`` ``(S, 24)``."""
    out = np.zeros((mult.shape[0], vecs.shape[1]))
    for s, combo in enumerate(choices):
        for i in combo:
            out[s] += (mult[s, i] - 1.0) * np.nan_to_num(vecs[i])
    return out
