"""Rapordaki sayıların pakete karşı denetimi."""
from fdo.inseason.number_check import check, packet_numbers, text_numbers

PACKET = {"players": [{"name": "Banchero", "season": {"PTS": 25.94, "FG_PCT": 0.4133, "gp": 23}},
                      {"name": "Clingan", "note": "son 5 maçta 31,5 dakika", "returns": "2026-11-20"}],
          "model": {"ecw_delta": 0.3341, "flag": True}}


def test_text_numbers_read_turkish_decimals_signs_and_skip_dates():
    got = [(v, d) for v, d, _ in text_numbers("25,9 sayı, %41,3 isabet; +0,33 kategori; −0,12; 20 Kasım'da döner")]
    assert got == [(25.9, 1), (41.3, 1), (0.33, 2), (-0.12, 2)]


def test_packet_numbers_include_numbers_inside_text_but_not_iso_dates():
    pool = packet_numbers(PACKET)
    assert 31.5 in pool and 23.0 in pool and 2026.0 not in pool and 1.0 not in pool   # bool sayı değil


def test_check_lists_only_numbers_missing_from_the_packet():
    report = {"headline": "Banchero 25,9 sayı ve %41,3 isabetle (23 maç) iyi; model +0,33 diyor.",
              "sections": [{"title": "Rol", "points": ["Clingan 31,5 dakika alıyor, 3 maçtır ilk beşte.",
                                                       "Takım 112,4 hücum reytinginde."]}],
              "counter_offers": [{"why": "27,5 sayılık bir yıldız ister."}], "watch": ["20 Kasım dönüşü"]}
    r = check(report, PACKET)
    assert r["checked"] == 7                                                    # 3 ve tarih denetlenmez
    assert [(u["value"], u["where"]) for u in r["unmatched"]] == [("112,4", "Rol"), ("27,5", "Karşı teklif")]
    assert "hücum" in r["unmatched"][0]["context"]
