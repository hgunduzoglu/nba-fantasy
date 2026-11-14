"""Teklifler ve cevapları: kabul gerekçesi eşiklerinin gerçek kayıtlarla ayarlanması için.

Kullanıcı bir teklifi "teklif ettim" diye kaydeder (``user_reported`` / ``trade_offer``): o andaki ölçüler (iki tarafın
kazancı, değer dengesi, rakibin gözünde oran, kabul gerekçesi düzeyi) kayda girer. Cevap ayrı bir kayıttır
(``offer_response``: kabul / ret / karşı teklif); günlük yalnız eklemeli olduğu için teklif değişmez, son cevap geçerlidir.

``acceptance`` kabul oranını kabul gerekçesi düzeyine ve rakibin gözündeki orana göre gruplar. Grup başına az teklif
varken oranlar belirsizdir; eşikler (``PERCEIVED_EVEN`` 0,95, ``max_view`` 1,25, ``min_view`` 0,80) ancak yeterli kayıtla
değiştirilmelidir (``scripts/calibrate_thresholds.py``).
"""

from __future__ import annotations

OUTCOMES = ("accepted", "rejected", "countered")
#: Rakibin gözünde oran grupları (üst sınır dahil değil); kodda kullanılan eşiklerin çevresi.
VIEW_BINS = ((0.0, 0.8), (0.8, 0.95), (0.95, 1.1), (1.1, 1.25), (1.25, float("inf")))


def offers(entries: list[dict], league_id: str | None = None) -> list[dict]:
    """Teklifler (eskiden yeniye), son cevabıyla: ``outcome`` accepted / rejected / countered ya da pending."""
    rows = [e for e in entries if e.get("kind") == "user_reported"
            and (league_id is None or e.get("league_id") == str(league_id))]
    answer: dict[str, dict] = {}
    for e in rows:
        if e["action"] == "offer_response" and e["request"].get("outcome") in OUTCOMES:
            answer[e["request"].get("about")] = e
    out = []
    for e in rows:
        if e["action"] != "trade_offer":
            continue
        a = answer.get(e["decision_id"])
        out.append({"decision_id": e["decision_id"], "created_at": e["created_at"], "league_id": e["league_id"],
                    "request": e["request"], "names": e["result"].get("names", {}),
                    "features": e["result"].get("features", {}),
                    "outcome": a["request"]["outcome"] if a else "pending",
                    "answered_at": a["created_at"] if a else None})
    return out


def _bin(view) -> str:
    if view is None:
        return "bilinmiyor"
    for lo, hi in VIEW_BINS:
        if lo <= view < hi:
            return f"{lo:.2f}–{hi:.2f}" if hi != float("inf") else f"≥ {lo:.2f}"
    return "bilinmiyor"


def acceptance(rows: list[dict]) -> dict[str, list[dict]]:
    """Cevaplanmış teklifler (karşı teklif kabul sayılmaz) için grup başına sayı ve kabul oranı."""
    done = [r for r in rows if r["outcome"] in OUTCOMES]
    out = {}
    for name, key in (("acceptability", lambda r: r["features"].get("acceptability") or "bilinmiyor"),
                      ("perceived_view", lambda r: _bin(r["features"].get("perceived_view")))):
        groups: dict[str, list[dict]] = {}
        for r in done:
            groups.setdefault(key(r), []).append(r)
        out[name] = [{"group": g, "n": len(v), "accepted": sum(r["outcome"] == "accepted" for r in v),
                      "rate": sum(r["outcome"] == "accepted" for r in v) / len(v)} for g, v in sorted(groups.items())]
    return out
