export type TurnstileStatus = "idle" | "pending" | "ready" | "unavailable" | "error";

export type ConsumeResult =
  | { ok: true; token: string }
  | { ok: false; reason: "sem token" | "indisponível" };

export interface TurnstileOptions {
  sitekey: string;
  callback: (token: string) => void;
  "expired-callback": () => void;
  "error-callback": () => void;
  language: string;
}

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: TurnstileOptions) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId?: string) => void;
    };
  }
}

const TURNSTILE_BASE = "https://challenges.cloudflare.com/turnstile/v0/api.js";
const TURNSTILE_SRC = `${TURNSTILE_BASE}?render=explicit`;
const POLL_MS = 50;
const LOAD_TIMEOUT_MS = 10_000;

let inflight: Promise<void> | null = null;

function turnstileReady(): boolean {
  return typeof window.turnstile?.render === "function";
}

/** Injeta o api.js do Turnstile uma única vez e resolve quando `window.turnstile` está pronto. */
export function loadTurnstile(): Promise<void> {
  if (turnstileReady()) return Promise.resolve();
  if (inflight) return inflight;
  const promise = new Promise<void>((resolve, reject) => {
    let settled = false;
    const ok = () => {
      if (settled) return;
      settled = true;
      inflight = null;
      resolve();
    };
    const fail = (err: Error) => {
      if (settled) return;
      settled = true;
      inflight = null;
      reject(err);
    };
    let script = document.querySelector<HTMLScriptElement>(`script[src^="${TURNSTILE_BASE}"]`);
    if (!script) {
      script = document.createElement("script");
      script.src = TURNSTILE_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", () => {
      if (turnstileReady()) ok();
    });
    script.addEventListener("error", () => {
      fail(new Error("falha ao carregar o script do Turnstile"));
    });
    const started = Date.now();
    const tick = () => {
      if (settled) return;
      if (turnstileReady()) return ok();
      if (Date.now() - started > LOAD_TIMEOUT_MS) {
        return fail(new Error("timeout ao carregar o script do Turnstile"));
      }
      setTimeout(tick, POLL_MS);
    };
    tick();
  });
  inflight = promise;
  return promise;
}

export class TurnstileController {
  widgetId: string | null = null;
  token: string | null = null;
  status: TurnstileStatus = "idle";
  private generation = 0;

  async render(container: HTMLElement, siteKey: string): Promise<void> {
    this.destroy();
    const generation = this.generation;
    try {
      await loadTurnstile();
      if (generation !== this.generation) return;
      if (typeof window.turnstile?.render !== "function") {
        console.error("window.turnstile.render indisponível após o script carregar");
        this.status = "unavailable";
        return;
      }
      this.widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        callback: (token: string) => {
          if (generation !== this.generation || !token) return;
          this.token = token;
          this.status = "ready";
        },
        "expired-callback": () => {
          if (generation !== this.generation) return;
          this.token = null;
          this.status = "idle";
        },
        "error-callback": () => {
          if (generation !== this.generation) return;
          this.token = null;
          this.status = "error";
        },
        language: "pt-br",
      });
      this.status = "pending";
    } catch (err) {
      console.error(err);
      if (generation !== this.generation) return;
      this.status = "unavailable";
    }
  }

  /** Token é de uso único: chamar em TODO submit, nunca reutilizar. */
  consume(): ConsumeResult {
    const token = this.token;
    if (token) {
      this.reset();
      return { ok: true, token };
    }
    return { ok: false, reason: this.status === "unavailable" ? "indisponível" : "sem token" };
  }

  reset(): void {
    this.token = null;
    if (this.widgetId === null) {
      this.status = "idle";
      return;
    }
    if (typeof window.turnstile?.reset === "function") {
      window.turnstile.reset(this.widgetId);
    }
    this.status = "pending";
  }

  destroy(): void {
    this.generation += 1;
    if (this.widgetId !== null && typeof window.turnstile?.remove === "function") {
      window.turnstile.remove(this.widgetId);
    }
    this.widgetId = null;
    this.token = null;
    this.status = "idle";
  }
}
