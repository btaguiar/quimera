import { defineConfig } from "@playwright/test";

// PW_CHANNEL=msedge (ou chrome) usa o navegador instalado quando o download
// do Chromium do Playwright não está disponível; sem ela, o Chromium padrão.
const channel = process.env.PW_CHANNEL || undefined;

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:5173",
    colorScheme: "dark",
    channel,
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});
