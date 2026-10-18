"""Yahoo ortalama auction fiyatı (AAV) içe aktarımı (README §13.12).

Kabul edilen biçimler: JSON (``players`` listesi ya da liste; ad alanı ``name``/``player``, fiyat alanı
``avg_cost``/``average_cost``/``avg_auction_cost``/``aav``/``cost``/``price``), başlıklı CSV/TSV (aynı ad ve
fiyat sütunları) ya da serbest metin satırları (``Nikola Jokić (DEN - C) $64.5`` gibi; satırdaki son sayı
fiyat). Ad eşleşmesi ``normalize_name`` ile; "Soyad, Ad" biçimi de denenir.
"""

from __future__ import annotations

import io
import json
import re

import pandas as pd

from fdo.ingest.load import normalize_name

NAME_KEYS = ("name", "player", "player_name", "full_name", "oyuncu")
COST_KEYS = ("avg_cost", "average_cost", "avg_auction_cost", "avg_salary", "aav", "auction_value", "avg $",
             "avg_price", "cost", "price", "salary", "value", "fiyat")
_NUM = re.compile(r"\$?\s*(\d+(?:[.,]\d+)?)")
_PAREN = re.compile(r"\([^)]*\)")


def _pick(cols, keys):
    low = {str(c).strip().lower(): c for c in cols}
    for k in keys:
        if k in low:
            return low[k]
    for k in keys:
        for lc, c in low.items():
            if k in lc:
                return c
    return None


def _records(text: str) -> list[tuple[str, float]]:
    t = text.strip()
    if t[:1] in "[{":
        data = json.loads(t)
        rows = data if isinstance(data, list) else next(v for v in data.values() if isinstance(v, list))
        df = pd.DataFrame(rows)
    else:
        first = t.splitlines()[0]
        sep = "\t" if "\t" in first else ("," if first.count(",") >= 1 and not _NUM.search(first) else None)
        df = pd.read_csv(io.StringIO(t), sep=sep) if sep else None
    if df is not None:
        nc, cc = _pick(df.columns, NAME_KEYS), _pick(df.columns, COST_KEYS)
        if nc is not None and cc is not None:
            cost = pd.to_numeric(df[cc].astype(str).str.replace("$", "", regex=False).str.replace(",", "."),
                                 errors="coerce")
            return [(str(n), float(c)) for n, c in zip(df[nc], cost) if pd.notna(c)]
    out = []
    for line in t.splitlines():
        line = line.strip()
        nums = _NUM.findall(line)
        if not line or not nums:
            continue
        cost = float(nums[-1].replace(",", "."))
        name = _PAREN.sub(" ", line)
        name = re.sub(r"\$?\s*\d+(?:[.,]\d+)?", " ", name)
        name = re.sub(r"\b(PG|SG|SF|PF|C|G|F|UTIL)(,(PG|SG|SF|PF|C|G|F))*\b", " ", name)
        name = re.sub(r"[-–|$%]", " ", name).strip()
        if name:
            out.append((name, cost))
    return out


def parse_costs(text: str, players: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Dönüş: ``player_id → fiyat`` ve eşleşmeyen adlar."""
    index: dict[str, str] = {}
    for pid, nm in zip(players["player_id"], players["name"]):
        index.setdefault(normalize_name(nm), str(pid))
    costs: dict[str, float] = {}
    unmatched = []
    for name, cost in _records(text):
        bare = " ".join(w for w in name.split() if not re.fullmatch(r"[A-Z]{2,4}", w))   # takım kodları
        cands = [name, bare]
        for n in (name, bare):
            if "," in n:
                last, _, first = n.partition(",")
                cands.append(f"{first} {last}")
        pid = None
        for c in cands:
            key = normalize_name(c)
            pid = index.get(key)
            if pid is None:                                    # baştaki sıra numarası / takım kodu
                key2 = " ".join(w for w in key.split() if not w.isdigit())
                pid = index.get(key2)
            if pid:
                break
        if pid is None:
            unmatched.append(name)
        else:
            costs.setdefault(pid, cost)
    return pd.Series(costs, name="avg_cost", dtype=float), unmatched
