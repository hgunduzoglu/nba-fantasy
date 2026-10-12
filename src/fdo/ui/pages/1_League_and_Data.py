"""Sayfa 1 — League & Data (README §8, §3, §5)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from fdo.config import REPO_ROOT
from fdo.ingest import load_dataset
from fdo.ingest.schema import LICENSE_STATUSES, MANIFEST_KINDS
from fdo.ingest.synthetic import write_synthetic
from fdo.ui import common

common.page("1 · League & Data", needs_data=False)
cfg = common.config()
DATA = REPO_ROOT / "data"

# --------------------------------------------------------------------- lig
st.header("Lig konfigürasyonu")
lg = cfg.league
left, right = st.columns(2)
with left:
    st.caption("Kesinleşmiş ayarlar (kilitli, `config/league.yaml`)")
    st.table(pd.DataFrame({
        "ayar": ["platform", "season", "teams", "my_seat", "rounds", "draft_type", "kategoriler",
                 "lower_is_better", "slotlar"],
        "değer": [lg.platform, lg.season, lg.teams, lg.my_seat, lg.rounds, lg.draft_type,
                  ", ".join(cfg.categories), ", ".join(sorted(cfg.lower_is_better)),
                  ", ".join(f"{k}×{v}" for k, v in cfg.roster.slots.items())],
    }).astype(str))
    trr = st.toggle("Third round reversal (3RR)", value=lg.third_round_reversal,
                    help="Varsayılan kapalı; açılırsa sıra ve turn'ler yeniden türetilir. Mock sıfırlanır.")
    if trr != lg.third_round_reversal:
        common.set_config(cfg.with_overrides({"league": {"third_round_reversal": trr}}))
        st.rerun()

with right:
    st.caption("Doğrulanmamış ayarlar (`unverified`) — `null` değerler sessizce varsayılana çevrilmez")
    un = cfg.unverified
    st.table(pd.DataFrame({"ayar": [f for f in vars(un)],
                           "değer": [str(v) for v in vars(un).values()]}))
    for f in un.null_fields():
        msg = {
            "pick_timer_seconds": "Pick süresi bilinmiyor → advisor hesap bütçesi doğrulanamaz (hızlı mod önerilir).",
            "position_limits_enforced_in_draft": "Yahoo'nun draft sırasında pozisyon sınırı uygulayıp "
                                                 "uygulamadığı doğrulanmadı → draft motorunda kısıt yok.",
            "lineup_lock": "Lineup kilit kuralı bilinmiyor → utilization tek katsayı (kalibre edilmemiş).",
            "il_slots": "IL/IL+ slotları draft kadrosuna dahil değil kabul edildi.",
        }.get(f, f"{f} = null")
        st.warning(msg)
    with st.expander("Doğrulanmamış ayarları bu oturum için düzenle"):
        tie = st.number_input("tie_value", 0.0, 1.0, float(un.tie_value or 0.5), 0.5)
        timer = st.number_input("pick_timer_seconds (0 = bilinmiyor)", 0, 600, int(un.pick_timer_seconds or 0))
        if st.button("Uygula"):
            common.set_config(cfg.with_overrides({"unverified": {
                "tie_value": tie, "pick_timer_seconds": timer or None}}))
            st.rerun()

st.session_state.seed = st.number_input("Oturum seed'i (mock, advisor, doldurma tabloları)",
                                        0, 2**31 - 1, int(st.session_state.seed))

# --------------------------------------------------------------------- veri
st.header("Veri")


def show_report(report) -> None:
    if report is None:
        return
    st.subheader("Validasyon raporu")
    st.write(report.summary())
    for e in report.errors:
        st.error(e)
    for w in report.warnings:
        st.warning(w)
    for n in report.notes:
        st.info(n)
    if report.name_issues:
        st.markdown("**Ad eşleme düzeltme tablosu** (fuzzy eşleşme otomatik uygulanmaz; öneridir)")
        st.dataframe(pd.DataFrame(report.name_issues).astype({"suggestions": str}), hide_index=True)
    if report.excluded:
        with st.expander(f"Havuz dışı oyuncular ({len(report.excluded)})"):
            st.dataframe(pd.DataFrame(sorted(report.excluded.items()), columns=["player_id", "neden"]),
                         hide_index=True)


def parse_column_map(text: str) -> dict | None:
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        st.error(f"Kolon eşleme JSON hatalı: {e}")
        st.stop()


tab_disk, tab_upload, tab_synth = st.tabs(["Diskten yükle", "CSV yükle + manifest", "Sentetik üret"])

with tab_disk:
    files = sorted([*DATA.glob("real/*.csv"), *DATA.glob("synthetic/*.csv")])
    if not files:
        st.info("`data/real/` ya da `data/synthetic/` altında CSV yok.")
    else:
        labels = [str(p.relative_to(REPO_ROOT)) for p in files]

        def pick(kind: str, optional: bool = False):
            opts = (["—"] if optional else []) + labels
            guess = next((i for i, l in enumerate(opts) if Path(l).name.startswith(kind)), 0)
            return st.selectbox(kind, opts, index=guess, key=f"disk_{kind}")

        c = st.columns(4)
        with c[0]:
            f_players = pick("players")
        with c[1]:
            f_proj = pick("projections")
        with c[2]:
            f_adp = pick("adp")
        with c[3]:
            f_var = pick("variance", optional=True)
        cmap = st.text_area("Kolon eşleme (opsiyonel JSON, ör. `{\"3PTM\": \"fg3m\"}`)", "", key="cmap_disk")
        if st.button("Yükle ve doğrula", type="primary"):
            ds, rep = load_dataset(REPO_ROOT / f_players, REPO_ROOT / f_proj, REPO_ROOT / f_adp,
                                   None if f_var == "—" else REPO_ROOT / f_var,
                                   parse_column_map(cmap), config=cfg)
            common.set_dataset(ds, rep)
            st.rerun()

with tab_upload:
    st.markdown(
        "Dosyalar `data/real/` altına (git'e girmez), manifest'ler `data/manifests/` altına yazılır. "
        "**Manifest olmadan dosya yüklenmez.** Kaynağın kullanım şartlarını okuyup kararınızı manifest'e "
        "siz yazarsınız; kod bunu doğrulayamaz, yalnızca kaydeder (§5.1–5.2)."
    )
    up = st.file_uploader("CSV dosyası", type=["csv"])
    if up is not None:
        with st.form("manifest"):
            kind = st.selectbox("kind", MANIFEST_KINDS)
            source_name = st.text_input("source_name", "")
            source_url = st.text_input("source_url", "")
            retrieved_at = st.date_input("retrieved_at", dt.date.today())
            retrieved_by = st.text_input("retrieved_by", "manual export")
            license_status = st.selectbox("license_status", LICENSE_STATUSES, index=2)
            license_notes = st.text_area("license_notes", "")
            basis = st.selectbox("basis", ["per_game", "total"])
            manifest_yaml = st.file_uploader("…ya da hazır manifest YAML", type=["yaml", "yml"])
            if st.form_submit_button("Kaydet"):
                (DATA / "real").mkdir(parents=True, exist_ok=True)
                (DATA / "manifests").mkdir(parents=True, exist_ok=True)
                target = DATA / "real" / up.name
                target.write_bytes(up.getvalue())
                if manifest_yaml is not None:
                    m = yaml.safe_load(manifest_yaml.getvalue()) or {}
                else:
                    m = {"file": str(target.relative_to(REPO_ROOT).as_posix()), "kind": kind,
                         "source_name": source_name, "source_url": source_url,
                         "retrieved_at": retrieved_at.isoformat(), "retrieved_by": retrieved_by,
                         "license_status": license_status, "license_notes": license_notes,
                         "season": cfg.league.season, "basis": basis, "is_synthetic": False}
                (DATA / "manifests" / f"{up.name}.yaml").write_text(
                    yaml.safe_dump(m, sort_keys=False, allow_unicode=True), encoding="utf-8")
                st.success(f"{target.relative_to(REPO_ROOT)} ve manifest'i kaydedildi. "
                           "'Diskten yükle' sekmesinden seçebilirsiniz.")

with tab_synth:
    c = st.columns(3)
    n = c[0].number_input("Oyuncu sayısı", 250, 1000, 400, 50)
    sseed = c[1].number_input("Seed", 0, 10_000, 7)
    as_of = c[2].date_input("as_of", dt.date.today())
    if st.button("Sentetik veri üret ve yükle", type="primary"):
        out = DATA / "synthetic"
        paths = write_synthetic(out, int(n), int(sseed), cfg, as_of.isoformat())
        ds, rep = load_dataset(paths["players"], paths["projections"], paths["adp"], config=cfg)
        common.set_dataset(ds, rep)
        st.rerun()

show_report(st.session_state.report)

ds = st.session_state.dataset
if ds is not None:
    st.subheader("Yüklü veri seti")
    st.caption(f"hash `{ds.content_hash}` · {common.sources_caption(ds)}")
    st.dataframe(pd.DataFrame([{**s} for s in ds.sources()]), hide_index=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Oyuncu (players.csv)", len(ds.players))
    c2.metric("Projeksiyonlu", len(ds.projections))
    c3.metric("Draft havuzu", len(ds.adp))
    st.markdown("**`adp_status` dağılımı** — ADP güven sınıfı (§5.6); σ çarpanı sınıfa göre büyür")
    counts = ds.adp["adp_status"].value_counts().reindex(["ok", "low_confidence", "imputed", "tail"]).fillna(0)
    st.bar_chart(counts.rename("oyuncu"), color="#2a78d6", horizontal=True)
    st.caption("Not: 16 takımlı ligin 145–208 arası seçimleri, çoğunlukla 12 takımlı ADP verisinin seyrek "
               "olduğu bölgeye düşer; geç turlarda ADP'den gelen olasılıklar daha belirsizdir.")
