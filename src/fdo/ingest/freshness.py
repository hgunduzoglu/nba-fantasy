"""Bileşen bazında veri güncelliği ve karar türüne göre çalışma durumu.

Tek bir "son güncelleme" yerine her bileşenin (kadro, oyuncu istatistikleri, sakatlık, haber...) kendi zamanı tutulur
(``fdo.ingest.timestamps``). Yaş, dosyanın kendi kaydındaki çekim zamanından (``captured_at``) hesaplanır; o yoksa
dosya adındaki çekim gününden, o da yoksa dosyanın diskte değiştiği andan. Son durumda ``basis="file"`` işaretlenir:
kaynağın zamanı bilinmiyor demektir.

Karar türleri ve durumlar:

* ``normal``: gereken bütün bileşenler eşiğin içinde.
* ``conditional``: sonuç gösterilir ama hangi bileşenin eski ya da eksik olduğu söylenir (ör. "oyuncu hâlâ boştaysa").
* ``hold``: karar bekletilir; önce şu bileşen yenilenmeli.

Eşikler (saat) **başlangıç varsayımıdır**, ölçülerek doğrulanmadı. ``config/freshness.yaml`` varsa onunla değişir::

    adddrop:
      rosters: [12, 36]       # bu yaşa kadar normal, sonra bu yaşa kadar koşullu, sonra bekletilir
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from fdo.config import REPO_ROOT
from fdo.ingest.timestamps import COMPONENTS, file_times

#: karar → bileşen → (normal üst sınırı, koşullu üst sınırı) saat. ``None``: yaşa bakılmaz, yalnız var olmalı.
DEFAULT_RULES: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "trade": {"rosters": (72, 168), "player_stats": (168, 336), "injuries": (48, 168),
              "league_settings": (None, None), "schedule": (None, None)},
    "adddrop": {"rosters": (12, 36), "player_stats": (72, 168), "injuries": (12, 36), "live_week": (12, 36)},
    "lineup": {"rosters": (6, 24), "injuries": (6, 24), "live_week": (6, 24), "schedule": (None, None)},
    "season": {"rosters": (72, 336), "results": (168, 336), "player_stats": (168, 336), "schedule": (None, None)},
}
LABELS = {"rosters": "Kadrolar", "player_stats": "Oyuncu istatistikleri ve kalan sezon projeksiyonu",
          "live_week": "Bu haftanın skoru, alım hakkı, waiver listesi", "results": "Biten haftaların sonuçları",
          "league_settings": "Lig ayarları", "standings": "Puan durumu", "injuries": "Sakatlık raporu (CBS)",
          "nba_logs": "NBA maç kayıtları", "news": "Haberler", "preseason_projection": "Sezon öncesi projeksiyon",
          "player_master": "Oyuncu listesi", "adp": "Yahoo ADP", "draft": "Lig draftı", "schedule": "NBA takvimi",
          "variance": "Tarihsel varyans", "fixtures": "Lig fikstürü", "transactions": "İşlem geçmişi"}
DECISIONS = {"trade": "Takas", "adddrop": "Add/drop", "lineup": "Kadro (lineup)", "season": "Sezon görünümü"}
SHORT = {"trade": "takas", "adddrop": "add/drop", "lineup": "lineup", "season": "sezon"}
REFRESH = {"rosters": "Yahoo'dan güncelle", "player_stats": "Yahoo'dan güncelle (projeksiyonlar açık)",
           "live_week": "Yahoo'dan güncelle", "results": "Yahoo'dan güncelle", "standings": "Yahoo'dan güncelle",
           "injuries": "Yahoo'dan güncelle (CBS raporu da çekilir)", "nba_logs": "Yahoo'dan güncelle",
           "news": "Haberleri yenile", "league_settings": "Lig ayarlarını yeniden içe aktar (league_info.json)",
           "schedule": "NBA takvimini yeniden çek (scripts/fetch_nba_schedule.py)"}
#: Bileşen birden çok dosyadaysa geçerli olan: adı en büyük (tarihli adlar) ya da özel seçim.
_CURRENT = {"nba_logs": lambda paths, season: [p for p in paths if season and season in p.name] or paths[-1:]}


def rules(path: str | Path | None = None) -> dict:
    """Varsayılan eşikler + ``config/freshness.yaml`` (varsa) üzerine yazılmış hâli."""
    out = {k: dict(v) for k, v in DEFAULT_RULES.items()}
    path = Path(path) if path else REPO_ROOT / "config" / "freshness.yaml"
    if path.exists():
        for decision, comps in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
            for comp, limits in (comps or {}).items():
                out.setdefault(decision, {})[comp] = tuple(limits) if limits is not None else (None, None)
    return out


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def components(directory: str | Path, season: str | None = None) -> dict[str, dict]:
    """Her bileşenin geçerli dosyası ve zamanları (``file_times``)."""
    directory = Path(directory)
    out = {}
    for pattern, comp in COMPONENTS:
        if comp in out:
            continue
        paths = sorted(p for p in directory.glob(pattern) if p.is_file() and not p.name.endswith(".tmp"))
        if comp == "standings":
            paths = [p for p in paths if p.name == "standings_live.csv"] or paths[-1:]
        if not paths:
            continue
        chosen = _CURRENT[comp](paths, season) if comp in _CURRENT else paths[-1:]
        out[comp] = {**file_times(chosen[-1]), "file": chosen[-1].name}
    return out


def ages(comps: dict[str, dict], now: dt.datetime) -> dict[str, dict]:
    """Bileşen → yaş (saat) ve dayanağı: ``captured`` (dosyadaki çekim zamanı), ``captured_on`` (dosya adındaki gün,
    gün sonu varsayılır), ``source`` (kaynak tarihi, gün sonu), ``file`` (disk zamanı; kaynak zamanı bilinmiyor)."""
    out = {}
    for comp, t in comps.items():
        when, basis = _parse(t.get("captured_at")), "captured"
        if when is None and t.get("captured_on"):
            when, basis = _parse(t["captured_on"] + "T23:59:59+00:00"), "captured_on"
        if when is None and t.get("source_as_of") and len(str(t["source_as_of"])) == 10:
            when, basis = _parse(t["source_as_of"] + "T23:59:59+00:00"), "source"
        if when is None:
            when, basis = _parse(t.get("file_modified_at")), "file"
        out[comp] = {**t, "label": LABELS.get(comp, comp), "basis": basis,
                     "as_of": when.isoformat(timespec="minutes") if when else None,
                     "age_hours": round(max(0.0, (now - when).total_seconds() / 3600), 1) if when else None}
    return out


def assess(aged: dict[str, dict], rule_set: dict | None = None, read_only: bool = False) -> dict[str, dict]:
    """Karar türü → ``{"state", "label", "reasons", "refresh"}``. ``read_only``: sunucuda yenileme bilgisayarda yapılır."""
    rule_set = rule_set or rules()
    rank = {"normal": 0, "conditional": 1, "hold": 2}
    out = {}
    for decision, comps in rule_set.items():
        state, reasons, actions = "normal", [], {}
        for comp, (ok_h, cond_h) in comps.items():
            c = aged.get(comp)
            label = LABELS.get(comp, comp)
            if c is None:
                s, why = "hold", f"{label} yok"
            elif ok_h is None or c["age_hours"] is None:
                s, why = "normal", ""
            elif c["age_hours"] <= ok_h:
                s, why = "normal", ""
            elif cond_h is not None and c["age_hours"] <= cond_h:
                s, why = "conditional", f"{label} {c['age_hours']:.0f} saatlik (normal ≤ {ok_h:.0f} sa)"
            else:
                s, why = "hold", f"{label} {c['age_hours']:.0f} saatlik (koşullu ≤ {cond_h:.0f} sa)"
            if s != "normal":
                reasons.append(why)
                actions.setdefault(REFRESH.get(comp, "Dosyayı yenile"), []).append(label)
                if c is not None and c.get("basis") == "file":
                    reasons[-1] += " — kaynak zamanı bilinmiyor, dosya zamanına göre"
            if rank[s] > rank[state]:
                state = s
        # aynı eylem bir kez: "Yahoo'dan güncelle (Kadrolar, Sakatlık raporu)"
        refresh = [(f"bilgisayarda {a[0].lower() + a[1:]}, sonra veriyi gönder" if read_only else a)
                   + f" ({', '.join(labels)})" for a, labels in actions.items()]
        out[decision] = {"state": state, "label": DECISIONS.get(decision, decision), "short": SHORT.get(decision, decision),
                         "reasons": reasons, "refresh": refresh}
    return out


def report(directory: str | Path, *, season: str | None = None, now: dt.datetime | None = None,
           read_only: bool = False, rule_path: str | Path | None = None) -> dict:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    aged = ages(components(directory, season), now)
    return {"now": now.isoformat(timespec="minutes"), "components": aged,
            "decisions": assess(aged, rules(rule_path), read_only),
            "assumption": "Eşikler başlangıç varsayımıdır; ölçülerek doğrulanmadı (config/freshness.yaml)."}
