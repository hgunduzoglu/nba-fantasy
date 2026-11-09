"""Veri sağlayıcıları: analiz verinin nereden geldiğini bilmez.

Her sağlayıcı aynı dosya sözleşmesine (``data/real`` düzeni: ``rosters.json``, ``player_stat_pages.json``,
``league_info.json``...) uyan bir dizin verir; analiz bu dizini ``fdo.trade.load_trade_data`` ile okur.

* ``ManualSnapshotProvider``: kullanıcının kendi çektiği güncel dosyalar (bugünkü akış: Yahoo senkronizasyonu kendi
  oturumuyla, CBS sakatlık raporu, NBA maç kayıtları). Varsayılan.
* ``ArchivedSnapshotProvider``: değiştirilemez arşivdeki bir parti (``fdo.ingest.archive``); geçmiş bir karar anını
  aynı girdilerle yeniden üretmek için.
* ``YahooApiProvider``: Yahoo API erişimi onaylanınca yazılacak. Şimdilik kapalı; hiçbir özellik ona bağlı değil.
  Onay gelse bile yalnız okuma kapsamı varsayılır: takas gönderme, add/drop, lineup değiştirme yok.
"""

from __future__ import annotations

from pathlib import Path

from fdo.ingest import archive

#: Sağlayıcının verebildiği veri parçaları.
PARTS = ("rosters", "player_stats", "ros_projection", "live_week", "waivers", "standings", "results",
         "league_settings", "transactions", "write")


class ProviderUnavailable(RuntimeError):
    pass


class ManualSnapshotProvider:
    name = "manual"

    def __init__(self, directory: str | Path):
        self.root = Path(directory)

    def capabilities(self) -> dict[str, bool]:
        have = {p.name for p in archive.archive_files(self.root)}
        return {"rosters": "rosters.json" in have, "player_stats": "player_stat_pages.json" in have,
                "ros_projection": "player_stat_pages.json" in have, "live_week": "yahoo_live.json" in have,
                "waivers": "yahoo_live.json" in have, "standings": any(n.startswith("standings") for n in have),
                "results": "matchups.json" in have, "league_settings": "league_info.json" in have,
                "transactions": "transactions.csv" in have, "write": False}

    def directory(self) -> Path:
        if not (self.root / "rosters.json").exists():
            raise ProviderUnavailable(f"{self.root}: rosters.json yok (önce Yahoo'dan güncelle ya da dosyaları içe aktar)")
        return self.root


class ArchivedSnapshotProvider:
    name = "archive"

    def __init__(self, directory: str | Path, batch_id: str, workdir: str | Path):
        self.root, self.batch_id, self.workdir = Path(directory), batch_id, Path(workdir)

    def manifest(self) -> dict:
        return archive.get(self.root, self.batch_id)

    def capabilities(self) -> dict[str, bool]:
        names = set(self.manifest()["files"])
        return {**{k: False for k in PARTS}, "rosters": "rosters.json" in names,
                "player_stats": "player_stat_pages.json" in names, "ros_projection": "player_stat_pages.json" in names,
                "live_week": "yahoo_live.json" in names, "league_settings": "league_info.json" in names}

    def directory(self) -> Path:
        m = self.manifest()
        if not m["complete"]:
            raise ProviderUnavailable(f"{self.batch_id}: parti eksik ({', '.join(m['missing'])}); analiz kurulamaz")
        target = self.workdir / self.batch_id
        if not target.exists():
            archive.restore(self.root, self.batch_id, target)
        return target


class YahooApiProvider:
    name = "yahoo_api"

    def capabilities(self) -> dict[str, bool]:
        return {k: False for k in PARTS}

    def directory(self) -> Path:
        raise ProviderUnavailable("Yahoo API erişimi henüz onaylanmadı; veri elle çekilen anlık görüntülerden gelir.")
