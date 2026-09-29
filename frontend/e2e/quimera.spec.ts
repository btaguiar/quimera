import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const fixture = (nome: string) =>
  JSON.parse(readFileSync(new URL(`./fixtures/${nome}`, import.meta.url), "utf-8"));

async function mockarApi(page: Page, opcoes: { leads?: unknown } = {}) {
  await page.route("**/config", (r) => r.fulfill({ json: { turnstile_site_key: null } }));
  await page.route("**/health", (r) =>
    r.fulfill({
      json: { status: "ok", version: "0.1.0", cache_mode: false, budget_remaining_bytes: 1073741824 },
    }),
  );
  await page.route("**/metrics", (r) => r.fulfill({ json: fixture("metrics.json") }));
  await page.route("**/leads", (r) =>
    r.fulfill({ json: opcoes.leads ?? fixture("leads-success.json") }),
  );
}

test("pedido vira resultado com ranking", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("pedido em português");
  await page.getByLabel(/pedido/i).fill("clínicas em Santo André");
  await page.getByRole("button", { name: /^analisar$/i }).click();
  await expect(page.getByText(/interpretação do pedido/i)).toBeVisible();
  const ranking = page.getByRole("region", { name: /ranking de empresas/i });
  await expect(ranking.getByText("CLINICA ALFA")).toBeVisible();
  await expect(ranking.getByText("87", { exact: true })).toBeVisible();
  await expect(page.getByText(/SELECT \* FROM/)).toBeVisible();
  await expect(page.getByText("33,0 MB").first()).toBeVisible();
  await page.screenshot({ path: "test-results/estado-resultado.png", fullPage: true });
});

test("chips de exemplo preenchem o pedido", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: /padarias artesanais/i }).click();
  await expect(page.getByLabel(/pedido/i)).toHaveValue(/padarias artesanais/);
});

test("recusa renderiza banner com motivo", async ({ page }) => {
  await mockarApi(page, { leads: fixture("leads-refusal.json") });
  await page.goto("/");
  await page.getByLabel(/pedido/i).fill("e-mails das clínicas");
  await page.getByRole("button", { name: /^analisar$/i }).click();
  await expect(page.getByText("pedido de dado pessoal (e-mail, telefone ou sócio)")).toBeVisible();
  await page.screenshot({ path: "test-results/estado-recusa.png", fullPage: true });
});

test("/metricas mostra suítes com acima e abaixo do limiar", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/metricas");
  await expect(page.getByRole("heading", { name: /métricas medidas/i })).toBeVisible();
  await expect(page.getByText(/acima do limiar/i).first()).toBeVisible();
  await expect(page.getByText("87,0%").first()).toBeVisible();
  await page.screenshot({ path: "test-results/estado-metricas.png", fullPage: true });
});

test("hero e empty state (baseline visual)", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/");
  await expect(page.getByText(/escreva um pedido acima/i)).toBeVisible();
  await page.screenshot({ path: "test-results/estado-hero.png", fullPage: true });
});
