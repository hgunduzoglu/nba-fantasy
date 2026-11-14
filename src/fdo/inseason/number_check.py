"""Yazılı rapordaki sayıların hesap paketine karşı denetimi (Claude'un detaylı analizi, README §13.29).

Rapor yalnız paketteki verileri kullanmalı; model yine de sayı uydurabilir ya da yanlış aktarabilir. Denetim rapordaki
her sayıyı paketteki sayılarla karşılaştırır: yazıldığı basamağa yuvarlanmış hâli (ya da yüzde olarak ×100) paketteki bir
değere eşitse "bulundu". Bulunamayan sayı yanlış demek değildir (iki değerin farkı, toplamı gibi türetilmiş olabilir);
kullanıcının kontrol etmesi için listelenir. Küçük tam sayılar (≤ 10: "2'ye 1", "3 maç") ve tarihler denetlenmez.
"""

from __future__ import annotations

import math
import re

MONTHS = ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık")
_NUM = re.compile(r"(?<![\w.,])([-+−]?)(%?)(\d+(?:[.,]\d+)?)(?![\d])")
_DATE_AFTER = re.compile(r"\s*(" + "|".join(MONTHS) + r")", re.I)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def packet_numbers(obj) -> list[float]:
    """Paketteki bütün sayılar (iç içe sözlük ve listeler; metin içindeki sayılar dahil, tarihler hariç)."""
    out: list[float] = []

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            if math.isfinite(float(x)):
                out.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            out.extend(v for v, _, _ in text_numbers(_ISO.sub(" ", x)))
    walk(obj)
    return out


def text_numbers(text: str) -> list[tuple[float, int, str]]:
    """Metindeki sayılar: (değer, ondalık basamak, yazıldığı biçim). Türkçe ondalık virgül; "%41,3" → 41.3."""
    out = []
    for m in _NUM.finditer(text):
        sign, _pct, body = m.groups()
        if _DATE_AFTER.match(text, m.end()):
            continue
        decimals = len(re.split(r"[.,]", body)[1]) if re.search(r"[.,]", body) else 0
        value = float(body.replace(",", "."))                   # binlik ayıraç kullanılmadığı varsayılır
        out.append((-value if sign in ("-", "−") else value, decimals, m.group(0)))
    return out


def _found(value: float, decimals: int, pool: list[float]) -> bool:
    tol = 0.5 * 10 ** -decimals + 1e-9
    target = abs(value)
    for v in pool:
        for cand in (abs(v), abs(v) * 100):
            if abs(round(cand, decimals) - target) <= 10 ** -decimals * 1.01 or abs(cand - target) <= tol:
                return True
    return False


def report_texts(report: dict) -> list[tuple[str, str]]:
    """Raporun metin alanları: (yer, metin)."""
    out = [("Özet", report.get("headline", ""))]
    for s in report.get("sections", []):
        out += [(s.get("title", "Bölüm"), p) for p in s.get("points", [])]
    out += [("Karşı teklif", c.get("why", "")) for c in report.get("counter_offers", [])]
    out += [("İzlenecekler", w) for w in report.get("watch", [])]
    return out


def check(report: dict, packet: dict) -> dict:
    """``{"checked": n, "unmatched": [{"value", "where", "context"}]}``: paketteki hiçbir değerle eşleşmeyen sayılar."""
    pool = packet_numbers(packet)
    checked, unmatched = 0, []
    for where, text in report_texts(report):
        for value, decimals, raw in text_numbers(text):
            if decimals == 0 and abs(value) <= 10:
                continue
            checked += 1
            if not _found(value, decimals, pool):
                i = text.find(raw)
                unmatched.append({"value": raw.strip(), "where": where,
                                  "context": text[max(0, i - 40): i + len(raw) + 40].strip()})
    return {"checked": checked, "unmatched": unmatched}
