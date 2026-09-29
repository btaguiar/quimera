const fmtNum = new Intl.NumberFormat("pt-BR");
const fmt1 = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const fmt2 = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function fmtBytes(b: number | null | undefined): string {
  if (b == null || !Number.isFinite(b)) return "—";
  if (b >= 1024 ** 3) return `${fmt2.format(b / 1024 ** 3)} GB`;
  return `${fmt1.format(b / 1024 ** 2)} MB`;
}

export function fmtUSD(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `US$ ${v.toFixed(6).replace(".", ",")}`;
}

export function fmtMs(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${fmtNum.format(Math.round(v))} ms`;
}

export function fmtNumOrDash(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : fmtNum.format(v);
}

export function fmtData(yyyymmdd: string | null | undefined): string {
  return /^\d{8}$/.test(yyyymmdd ?? "")
    ? `${yyyymmdd!.slice(6, 8)}/${yyyymmdd!.slice(4, 6)}/${yyyymmdd!.slice(0, 4)}`
    : "—";
}

export function fmtPct(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : `${fmt1.format(v * 100)}%`;
}
