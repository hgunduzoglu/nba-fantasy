import type { Meta, StrategyIn } from "../types";

export type StrategyChoice =
  | { kind: "balanced" }
  | { kind: "preset"; name: string }
  | { kind: "auto"; n: 1 | 2 }
  | { kind: "custom"; weights: number[] };

export const BALANCED: StrategyChoice = { kind: "balanced" };

export function toStrategyIn(c: StrategyChoice): StrategyIn | null {
  switch (c.kind) {
    case "preset": return { preset: c.name };
    case "auto": return { auto_punt: c.n };
    case "custom": return { name: "Özel", weights: c.weights };
    default: return null;
  }
}

export function strategyLabel(c: StrategyChoice): string {
  switch (c.kind) {
    case "preset": return c.name;
    case "auto": return c.n === 1 ? "Otomatik: en zayıf kategoriyi punt" : "Otomatik: en zayıf iki kategoriyi punt";
    case "custom": return "Özel ağırlıklar";
    default: return "Dengeli";
  }
}

function encode(c: StrategyChoice): string {
  if (c.kind === "preset") return `preset:${c.name}`;
  if (c.kind === "auto") return `auto:${c.n}`;
  return c.kind;
}

/** Strateji seçici: dengeli, hazır punt'lar, otomatik punt (takım profilinden) ya da özel ağırlıklar (0–3). */
export function StrategyPicker({ meta, value, onChange, label = "Strateji", autoHint }: {
  meta: Meta; value: StrategyChoice; onChange: (c: StrategyChoice) => void; label?: string; autoHint?: string;
}) {
  const pick = (v: string) => {
    if (v === "balanced") onChange(BALANCED);
    else if (v === "custom") onChange({ kind: "custom", weights: value.kind === "custom" ? value.weights : Array(9).fill(1) });
    else if (v.startsWith("auto:")) onChange({ kind: "auto", n: Number(v.slice(5)) as 1 | 2 });
    else onChange({ kind: "preset", name: v.slice(7) });
  };
  return (
    <div className="field">
      <span>{label}</span>
      <select className="select" value={encode(value)} onChange={(e) => pick(e.target.value)}
              title={value.kind === "auto" ? autoHint ?? "Takımın kategori profilinden en zayıf kategori(ler) punt kabul edilir (varsayım)." : undefined}>
        <option value="balanced">Dengeli</option>
        <optgroup label="Otomatik (takım profilinden)">
          <option value="auto:1">Otomatik: en zayıf kategoriyi punt</option>
          <option value="auto:2">Otomatik: en zayıf iki kategoriyi punt</option>
        </optgroup>
        <optgroup label="Hazır punt">
          {meta.presets.filter((p) => p.name !== "Dengeli").map((p) => <option key={p.name} value={`preset:${p.name}`}>{p.name}</option>)}
        </optgroup>
        <option value="custom">Özel ağırlıklar…</option>
      </select>
      {value.kind === "custom" && (
        <div className="weights" role="group" aria-label="Kategori ağırlıkları (0 = punt, 1 = normal, 3 = üç kat)">
          {meta.categories.map((c, i) => (
            <label key={c.key}>
              <span>{c.label}</span>
              <input className="num-input" type="number" min={0} max={3} step={0.25} value={value.weights[i]}
                     onChange={(e) => {
                       const w = [...value.weights];
                       w[i] = Math.max(0, Math.min(3, Number(e.target.value) || 0));
                       if (w.some((x) => x > 0)) onChange({ kind: "custom", weights: w });
                     }} />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
