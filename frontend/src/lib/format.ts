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
  const m = /^(\d{4})-?(\d{2})-?(\d{2})$/.exec(yyyymmdd ?? "");
  if (!m) return "—";
  const [, ano, mes, dia] = m;
  return `${dia}/${mes}/${ano}`;
}

export function fmtPct(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : `${fmt1.format(v * 100)}%`;
}

/** Data/hora ISO do eval (``2026-09-26T11:21:58+00:00``) em UTC, sem depender do fuso do navegador. */
export function fmtDataHora(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(t)) return "—";
  const d = new Date(t);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

/** Capital 0 (ou negativo) e o sentinela 999.999.999.999 significam "não
 * informado" no cadastro da Receita (docs/schema.md), não capital zero. */
export const CAPITAL_SENTINELA = 999_999_999_999;

export function fmtCapital(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v <= 0 || v >= CAPITAL_SENTINELA) return "não informado";
  return fmtNum.format(v);
}
