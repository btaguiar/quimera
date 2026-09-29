import { describe, expect, it } from "vitest";
import { fmtBytes, fmtData, fmtMs, fmtNumOrDash, fmtPct, fmtUSD } from "@/lib/format";

describe("fmtBytes", () => {
  it("formata MB com uma casa", () => {
    expect(fmtBytes(33 * 1024 ** 2)).toBe("33,0 MB");
  });
  it("formata GB com duas casas", () => {
    expect(fmtBytes(1.5 * 1024 ** 3)).toBe("1,50 GB");
  });
  it("devolve traço quando ausente ou inválido", () => {
    expect(fmtBytes(null)).toBe("—");
    expect(fmtBytes(Number.NaN)).toBe("—");
  });
});

describe("fmtUSD", () => {
  it("mostra 6 casas com vírgula", () => {
    expect(fmtUSD(0.000123)).toBe("US$ 0,000123");
  });
  it("devolve traço quando ausente", () => {
    expect(fmtUSD(undefined)).toBe("—");
  });
});

describe("fmtMs", () => {
  it("arredonda e formata em pt-BR", () => {
    expect(fmtMs(4123.4)).toBe("4.123 ms");
  });
  it("devolve traço quando ausente", () => {
    expect(fmtMs(null)).toBe("—");
  });
});

describe("fmtData", () => {
  it("converte AAAAMMDD em DD/MM/AAAA", () => {
    expect(fmtData("20150110")).toBe("10/01/2015");
  });
  it("devolve traço para formato errado", () => {
    expect(fmtData("2015")).toBe("—");
    expect(fmtData(null)).toBe("—");
  });
});

describe("fmtPct", () => {
  it("mostra 0-1 como porcentagem com uma casa", () => {
    expect(fmtPct(0.955)).toBe("95,5%");
  });
});

describe("fmtNumOrDash", () => {
  it("formata inteiros e protege nulos", () => {
    expect(fmtNumOrDash(20)).toBe("20");
    expect(fmtNumOrDash(null)).toBe("—");
  });
});
