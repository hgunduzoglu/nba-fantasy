import { useMemo, useState } from "react";
import type { Category, CategoryKey, Player, Source } from "../types";
import { fmtDelta, fmtNum, fmtStat, returnText, zClass, zLabel } from "../format";

/** Maç sayısı; kalan sezon maçı oynama oranıyla kısıldıysa * ve açıklama. */
export function GpCell({ p }: { p: Player }) {
  const d = p.durability;
  return (
    <td title={d ? `Yahoo ${fmtNum(d.yahoo_gp, 0)} maç veriyor; beklenen oynama oranı %${Math.round(d.rate * 100)} × ${d.games_left} kalan maç` : undefined}>
      {fmtNum(p.gp, 0)}{d && <span className="muted">*</span>}
    </td>
  );
}

type SortKey = "order" | "name" | "gp" | "value" | "perceived" | CategoryKey;

interface Props {
  title: string;
  subtitle?: string;
  players: Player[] | null;
  categories: Category[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  loading?: boolean;
  error?: string | null;
  /** Bu sezon / sezon öncesi seçiliyken Değer'in yanında algılanan değer sütunu gösterilir. */
  source?: Source;
}

/** Algılanan − kalan sezon değeri (piyasa birimi): + olduğundan iyi görünüyor, − olduğundan kötü. */
function edgeOf(p: Player): number | null {
  return p.perceived_value != null && p.value != null ? p.perceived_value - p.value : null;
}

function PerceivedCell({ p, label }: { p: Player; label: string }) {
  const edge = edgeOf(p);
  if (p.perceived_value == null || p.perceived_rank == null || edge === null) return <td className="muted">–</td>;
  const diff = p.rank != null ? Math.round(p.rank - p.perceived_rank) : 0;   // + = algıda daha üst sırada
  const tip = `${label}: ${p.perceived_rank.toFixed(0)}. sıra → piyasada ${fmtNum(p.perceived_value)} değer görür. `
    + `Kalan sezon: ${p.rank?.toFixed(0) ?? "–"}. (${fmtNum(p.value)}). Fark ${fmtDelta(edge, 2)}`
    + (edge >= 0.5 ? ": olduğundan iyi görünüyor → satmak için iyi zaman." : edge <= -0.5 ? ": olduğundan kötü görünüyor → almak için iyi zaman." : ": aşağı yukarı doğru fiyatlanmış.")
    + (p.perceived_fallback ? " Bu sezon 3 maçtan az oynadığı için sezon öncesi sırası kullanıldı." : "");
  const cls = edge >= 1 ? "perc-over" : edge <= -1 ? "perc-under" : "";
  return (
    <td title={tip} className={cls}>
      {fmtNum(p.perceived_value)} <span className="psub">({p.perceived_rank.toFixed(0)}{p.perceived_fallback ? "*" : ""})</span>
      {Math.abs(edge) >= 0.5 && diff !== 0 && <div className="psub">{diff > 0 ? `▲ ${diff} sıra` : `▼ ${-diff} sıra`}</div>}
    </td>
  );
}

export function StatusBadges({ p }: { p: Player }) {
  const ret = returnText(p);
  return (
    <>
      {p.il && <span className="badge il" title="Sakatlık listesinde (IL)">IL</span>}
      {p.status === "O" && <span className="badge out" title={p.injury?.text || "Out"}>O</span>}
      {(p.status === "Q" || p.status === "GTD" || p.status === "DTD") && (
        <span className="badge q" title={p.injury?.text || "Questionable"}>{p.status}</span>
      )}
      {p.status === "NA" && <span className="badge il" title="Takımda aktif değil">NA</span>}
      {!p.modeled && <span className="badge il" title="Kalan sezon projeksiyonu eksik">ROS?</span>}
      {ret && p.injury?.kind !== "day_to_day" && <span className="psub" style={{ marginLeft: 6 }}>{ret}</span>}
    </>
  );
}

export function RosterTable({ title, subtitle, players, categories, selected, onToggle, loading, error, source }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "order", dir: 1 });

  const rows = useMemo(() => {
    if (!players) return [];
    const list = players.map((p, i) => ({ p, i }));
    if (sort.key === "order") return list;
    const val = (p: Player): number | string => {
      if (sort.key === "name") return p.name;
      if (sort.key === "gp") return p.gp ?? -1;
      if (sort.key === "value") return p.value ?? -1;
      if (sort.key === "perceived") return edgeOf(p) ?? -Infinity;
      const v = p.stats[sort.key as CategoryKey];
      if (v === null || v === undefined) return -Infinity;
      return sort.key === "TOV" ? -v : v;          // TO: az olan önce gelsin ("iyi" sırası)
    };
    return [...list].sort((a, b) => {
      const x = val(a.p), y = val(b.p);
      if (typeof x === "string" && typeof y === "string") return sort.dir * x.localeCompare(y, "tr");
      return sort.dir * ((y as number) - (x as number));
    });
  }, [players, sort]);

  const perceived = (players ?? []).some((p) => p.perceived_value != null);
  const pLabel = source === "preseason" ? "Sezon öncesi algısı" : "Bu sezon algısı";
  const header = (key: SortKey, label: string, cls = "", tip?: string) => (
    <th
      className={cls}
      title={tip}
      aria-sort={sort.key === key ? (sort.dir === 1 ? "descending" : "ascending") : undefined}
      onClick={() => setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: 1 }))}
    >
      {label}
      {sort.key === key ? (sort.dir === 1 ? " ↓" : " ↑") : ""}
    </th>
  );

  return (
    <div className="card">
      <div className="card-h">
        <h2>{title}</h2>
        {subtitle && <span className="muted">{subtitle}</span>}
        {loading && <span className="spinner" aria-label="yükleniyor" />}
      </div>
      {error && <div className="banner err" style={{ margin: 12 }}>{error}</div>}
      <div className="table-wrap">
        <table className="roster">
          <thead>
            <tr>
              <th className="l" onClick={() => setSort({ key: "order", dir: 1 })} title="Varsayılan sıra" />
              {header("name", "Oyuncu", "l")}
              {header("gp", "GP", "", source === "ros"
                ? "Kalan sezon maçı; * Yahoo'nun verdiği maç sezon öncesi oynama oranıyla kısıldı (üzerine gel)"
                : "Maç sayısı (seçili kaynakta)")}
              {categories.map((c) => header(c.key, c.label, "", `${c.label} — maç başı`))}
              {header("value", "Değer", "", "Kalan sezon dengeli değeri (yedek seviyesine göre); parantezde ligdeki sıra")}
              {perceived && header("perceived", pLabel, "",
                `${source === "preseason" ? "Sezon öncesi isim değerine (ligin draft fiyatı ve Yahoo ADP'si)" : "Bu sezonun maç başı rakamlarına"} bakan menajerin gözündeki sıra (parantezde) ve bu sıranın kalan sezon piyasasındaki karşılığı. ▲ olduğundan iyi görünüyor (sat), ▼ olduğundan kötü (al). Tıkla: farka göre sırala.`)}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ p }) => {
              const sel = selected.has(p.id);
              return (
                <tr key={p.id} className={(sel ? "sel " : "") + (p.il ? "dim" : "")} onClick={() => onToggle(p.id)}
                    aria-selected={sel}>
                  <td className="l"><span className="box">{sel ? "✓" : ""}</span></td>
                  <td className="l">
                    <div><span className="pname">{p.name}</span><StatusBadges p={p} /></div>
                    <div className="psub">{p.nba_team} · {p.positions.filter((x) => !["IL", "Util", "UTIL"].includes(x)).join(", ")}</div>
                  </td>
                  <GpCell p={p} />
                  {categories.map((c) => {
                    const z = p.z[c.key];
                    const tip = c.key === "FG_PCT" && p.attempts.fga
                      ? `${fmtNum(p.attempts.fgm)}/${fmtNum(p.attempts.fga)} · ${zLabel(z)}`
                      : c.key === "FT_PCT" && p.attempts.fta
                        ? `${fmtNum(p.attempts.ftm)}/${fmtNum(p.attempts.fta)} · ${zLabel(z)}`
                        : `${zLabel(z)}${z !== null ? ` (z ${z.toFixed(2)})` : ""}`;
                    return <td key={c.key} className={"stat " + zClass(z)} title={tip}>{fmtStat(c.key, p.stats[c.key])}</td>;
                  })}
                  <td title={p.rank ? `Ligde ${p.rank.toFixed(0)}. (kalan sezon değeri)` : ""}>
                    {fmtNum(p.value)} <span className="psub">{p.rank ? `(${p.rank.toFixed(0)})` : ""}</span>
                  </td>
                  {perceived && <PerceivedCell p={p} label={pLabel} />}
                </tr>
              );
            })}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={categories.length + (perceived ? 5 : 4)} className="empty">Oyuncu yok</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="legend">
        <span>Renk: oyuncunun o kategorideki seviyesi</span>
        <span><i className="z3" />Elite</span><span><i className="z2" />Great</span><span><i className="z1" />Good</span>
        <span><i style={{ background: "var(--mid)" }} />Avg</span><span><i className="zm2" />Below</span><span><i className="zm3" />Poor</span>
        <span>· TO'da az olan iyidir · satıra tıkla = takasa ekle</span>
        {perceived && <span>· Algı: <b className="perc-over">kalın turuncu</b> olduğundan iyi görünüyor (sat), <b className="perc-under">kalın mor</b> olduğundan kötü (al); * = 3 maçtan az, sezon öncesi</span>}
      </div>
    </div>
  );
}
