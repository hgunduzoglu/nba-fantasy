"""Yahoo Fantasy sayfalarının HTML ayrıştırıcıları (README §13.20).

Standart kütüphanenin ``html.parser``'ı ile küçük bir ağaç kurulur; ayrıştırıcılar sınıf, kimlik ve
bağlantılardan okur. Çıktılar mevcut anlık görüntülerin biçimindedir (``rosters.json`` takım/slot,
``player_stat_pages.json`` sayfa/tablo), böylece ``load_trade_data`` değişmeden okur.

Sayfalar: lig ana sayfası (puan durumu, haftanın eşleşmeleri, kullanıcının takımı), başlangıç kadroları,
eşleşme (``date=totals``: haftanın şu ana kadarki takım toplamları), takım sayfası (haftalık alım hakkı,
FAB) ve oyuncu listesi (sezon toplamı / kalan sezon projeksiyonu, kadro durumu, waiver tarihi).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterator

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLOCK = {"div", "p", "li", "ul", "ol", "tr", "table", "br", "h1", "h2", "h3", "h4", "section", "header"}
_SKIP = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.S | re.I)
_TEAM_LINK = re.compile(r"/nba/(\d+)/(\d+)/?$")
_REC = re.compile(r"^\s*(\d+)-(\d+)-(\d+)\s*$")
_TEAM_POS = re.compile(r"^([A-Z]{2,4}) - ([A-Za-z,]+)$")
_WAIVER = re.compile(r"^W \((\w{3}) (\d{1,2})\)$")
#: Eşleşme tablosu başlığı → ``fdo.inseason.weekly.ACC_FIELDS`` adları.
TOTALS = {"3PTM": "fg3m", "PTS": "pts", "REB": "reb", "AST": "ast", "ST": "stl", "BLK": "blk", "TO": "tov"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list = field(default_factory=list)          # Node | str

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def iter(self, tag: str | None = None) -> Iterator[Node]:
        for c in self.children:
            if isinstance(c, Node):
                if tag is None or c.tag == tag:
                    yield c
                yield from c.iter(tag)

    def find_all(self, tag: str | None = None, cls: str | None = None, **attrs) -> list[Node]:
        return [n for n in self.iter(tag) if (cls is None or cls in n.classes)
                and all(n.attrs.get(k.rstrip("_")) == v for k, v in attrs.items())]

    def find(self, tag: str | None = None, cls: str | None = None, **attrs) -> Node | None:
        return next(iter(self.find_all(tag, cls, **attrs)), None)

    def text(self) -> str:
        """Tarayıcının ``innerText``'ine yakın: blok öğeler satır ayırır, satır içi boşluklar teklenir."""
        parts: list[str] = []

        def walk(n: Node) -> None:
            block = n.tag in BLOCK or "D-b" in n.classes
            if block:
                parts.append("\n")
            for c in n.children:
                if isinstance(c, Node):
                    walk(c)
                else:
                    parts.append(c)
            if block:
                parts.append("\n")

        walk(self)
        lines = (re.sub(r"\s+", " ", ln).strip() for ln in "".join(parts).split("\n"))
        return "\n".join(ln for ln in lines if ln)

    def links(self) -> list[str]:
        return [a.attrs["href"] for a in self.iter("a") if a.attrs.get("href")]


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(html: str) -> Node:
    b = _Builder()
    b.feed(_SKIP.sub("", html))
    b.close()
    return b.root


# ------------------------------------------------------------------ ortak parçalar
def table_rows(table: Node) -> tuple[list[list[str]], list[Node]]:
    """(başlık satırları metinleri, gövde satırları); ``thead`` yoksa ilk satır başlıktır."""
    head = table.find("thead")
    body = table.find("tbody")
    header_rows = [[c.text() for c in tr.children if isinstance(c, Node) and c.tag in ("th", "td")]
                   for tr in (head.iter("tr") if head else [])]
    rows = list((body or table).iter("tr"))
    if not head and rows:
        header_rows = [[c.text() for c in rows[0].children if isinstance(c, Node) and c.tag in ("th", "td")]]
        rows = rows[1:]
    return header_rows, rows


def cells(tr: Node) -> list[Node]:
    return [c for c in tr.children if isinstance(c, Node) and c.tag in ("td", "th")]


def team_id_of(node: Node, league_id: str | None = None) -> str | None:
    for href in node.links():
        m = _TEAM_LINK.search(href.split("?")[0])
        if m and (league_id is None or m.group(1) == str(league_id)):
            return m.group(2)
    return None


def player_info(cell: Node) -> dict:
    """Oyuncu hücresi: kimlik, ad, NBA takımı, pozisyonlar, sakatlık durumu, maç metni."""
    a = next((n for n in cell.iter("a") if "name" in n.classes and n.attrs.get("data-ys-playerid")), None)
    if a is None:
        return {}
    team_pos = next((n.text() for n in cell.find_all("span", "Fz-xxs") if _TEAM_POS.match(n.text())), "")
    m = _TEAM_POS.match(team_pos)
    status = cell.find("span", "ysf-player-status")
    status_span = status.find("span") if status else None
    game = cell.find("span", "ysf-game-status")
    return {"player_id": a.attrs["data-ys-playerid"], "player_name": a.text(),
            "player_url": a.attrs.get("href", ""), "team_positions": team_pos,
            "nba_team": m.group(1) if m else "", "eligible_positions": m.group(2).split(",") if m else [],
            "status": status.text() if status else None,
            "status_description": status_span.attrs.get("title") if status_span else None,
            "game": game.text() if game else ""}


def counts(text: str) -> tuple[float, float]:
    made, att = (str(text).split("/") + [""])[:2]
    num = lambda x: float(x.replace(",", "")) if x.strip() not in ("", "-", "--") else float("nan")
    return num(made), num(att)


def waiver_date(roster_status: str, today: dt.date) -> dt.date | None:
    """``"W (Nov 9)"`` → tarih (yıl: ``today``'den önceki bir aya düşerse sonraki yıl)."""
    m = _WAIVER.match(str(roster_status).strip())
    if not m:
        return None
    month = dt.datetime.strptime(m.group(1), "%b").month
    d = dt.date(today.year, month, int(m.group(2)))
    return d.replace(year=today.year + 1) if (today - d).days > 180 else d


# ------------------------------------------------------------------ sayfalar
def parse_league_home(html: str, league_id: str) -> dict:
    """Puan durumu (takım → sıra, W-L-T, FAB, waiver sırası, hamle), haftanın eşleşmeleri, kullanıcının takımı."""
    root = parse(html)
    out: dict = {"standings": [], "week": None, "matchups": [], "my_team": None}
    table = root.find("table", id="standingstable")
    if table is not None:
        header, rows = table_rows(table)
        h = header[-1] if header else []
        col = lambda name: h.index(name) if name in h else None
        for tr in rows:
            cs = cells(tr)
            tid = team_id_of(tr, league_id)
            rec = _REC.match(cs[col("W-L-T")].text()) if col("W-L-T") is not None else None
            if not (tid and rec):
                continue
            row = {"team_id": tid, "team_name": cs[col("Team")].text() if col("Team") is not None else "",
                   "wins": int(rec.group(1)), "losses": int(rec.group(2)), "ties": int(rec.group(3))}
            for key, name in (("rank", "Rank"), ("waiver_priority", "Waiver"), ("moves", "Moves")):
                if col(name) is not None and cs[col(name)].text().isdigit():
                    row[key] = int(cs[col(name)].text())
            if col("Waiver Bdgt") is not None and (fab := re.sub(r"[^\d]", "", cs[col("Waiver Bdgt")].text())):
                row["fab"] = int(fab)
            out["standings"].append(row)
    seen = set()
    for href in root.links():
        m = re.search(rf"/nba/{league_id}/matchup\?week=(\d+)&mid1=(\d+)&mid2=(\d+)", href)
        if m and (m.group(2), m.group(3)) not in seen:
            seen.add((m.group(2), m.group(3)))
            out["week"] = int(m.group(1))
            out["matchups"].append((m.group(2), m.group(3)))
        if mine := re.search(rf"/nba/{league_id}/(\d+)/editteaminfo", href):
            out["my_team"] = mine.group(1)
    return out


def parse_starting_rosters(html: str, league_id: str) -> list[dict]:
    """``rosters.json`` takım listesi: ``team_id, team_name, team_url, slots[...]``."""
    root = parse(html)
    names = {}
    for p in root.find_all("p", "Fz-med"):
        if (tid := team_id_of(p, league_id)) is not None:
            names[tid] = next((a.text() for a in p.iter("a") if a.text()), "")
    teams = []
    for table in root.iter("table"):
        m = re.match(r"Tst-team-(\d+)$", table.attrs.get("id", ""))
        if not m:
            continue
        tid = m.group(1)
        _, rows = table_rows(table)
        slots = []
        for k, tr in enumerate(rows, start=1):
            cs = cells(tr)
            if len(cs) < 2:
                continue
            slot = cs[0].text()
            info = player_info(cs[1])
            if not info:
                continue                      # (Empty)
            slots.append({**info, "raw_text": f"{slot}\t\n{cs[1].text()}", "slot": slot, "slot_index": k,
                          "is_bench": slot == "BN", "is_injury_slot": slot in ("IL", "IL+")})
        teams.append({"team_id": tid, "team_name": names.get(tid, ""),
                      "team_url": f"https://basketball.fantasysports.yahoo.com/nba/{league_id}/{tid}", "slots": slots})
    return teams


def parse_matchup(html: str, league_id: str) -> list[dict]:
    """Eşleşme tablosu: her takım için ``team_id, team_name, totals{fgm..tov}, category_wins``."""
    root = parse(html)
    table = root.find("table", "Datatable")
    if table is None:
        return []
    header, rows = table_rows(table)
    h = header[-1]
    out = []
    for tr in rows:
        cs = cells(tr)
        tid = team_id_of(tr, league_id)
        if tid is None or len(cs) < len(h):
            continue
        totals = {}
        for name, (mk, at) in (("FGM/A*", ("fgm", "fga")), ("FTM/A*", ("ftm", "fta"))):
            totals[mk], totals[at] = counts(cs[h.index(name)].text())
        for name, key in TOTALS.items():
            totals[key] = counts(cs[h.index(name)].text())[0]
        wins = cs[-1].text()
        out.append({"team_id": tid, "team_name": cs[0].text(), "totals": totals,
                    "category_wins": int(wins) if wins.isdigit() else None})
    return out


def parse_team_page(html: str) -> dict:
    """Kullanıcının takım sayfası: bu hafta kullanılan alım hakkı, IL doluluğu, FAB bütçesi."""
    text = parse(html).text()
    out = {}
    if m := re.search(r"You have used (\d+) of your (\d+) player adds for this week", text):
        out["adds_used"], out["adds_limit"] = int(m.group(1)), int(m.group(2))
    if m := re.search(r"You have used (\d+) of (\d+) IL positions", text):
        out["il_used"], out["il_slots"] = int(m.group(1)), int(m.group(2))
    if m := re.search(r"Waiver Budget: \$(\d+)", text):
        out["fab"] = int(m.group(1))
    return out


def parse_player_table(html: str, league_id: str | None = None) -> dict | None:
    """Oyuncu listesi tablosu ``player_stat_pages.json``'daki ``table`` biçiminde; satırlara kadro durumu,
    sahip takım ve waiver metni de eklenir. Tablo yoksa ``None``."""
    root = parse(html)
    table = next((t for t in root.iter("table") if "Roster Status" in t.text()[:2000]
                  and t.find("thead") is not None), None)
    if table is None:
        return None
    header, rows = table_rows(table)
    h = header[-1]
    rs = h.index("Roster Status") if "Roster Status" in h else None
    out_rows = []
    for tr in rows:
        cs = cells(tr)
        info = next((player_info(c) for c in cs if c.find("a", "name") is not None), {})
        if not info:
            continue
        row = {"cells": [c.text() for c in cs], "player_id": info["player_id"], "player_name": info["player_name"],
               "nba_team": info["nba_team"], "positions": info["eligible_positions"], "status": info["status"] or ""}
        if rs is not None and rs < len(cs):
            row["roster_status"] = cs[rs].text()
            row["owner_team_id"] = team_id_of(cs[rs], league_id)
        out_rows.append(row)
    return {"headers": header, "rows": out_rows}
