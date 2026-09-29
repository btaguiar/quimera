export type TurnstileStatus = "idle" | "ready" | "unavailable" | "error";

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
    };
  }
}

export class TurnstileController {
  widgetId: string | null = null;
  token: string | null = null;
  status: TurnstileStatus = "idle";

  render(container: HTMLElement, siteKey: string): void {
    if (typeof window.turnstile?.render !== "function") {
      this.status = "unavailable";
      return;
    }
    try {
      this.widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        callback: (token: string) => {
          this.token = token;
          this.status = "ready";
        },
        "expired-callback": () => {
          this.token = null;
          this.status = "idle";
        },
        "error-callback": () => {
          this.token = null;
          this.status = "error";
        },
        language: "pt-br",
      });
      this.status = "ready";
    } catch {
      this.status = "unavailable";
    }
  }

  /** Token é de uso único: chamar em TODO submit, nunca reutilizar. */
  consume(): string | null {
    const token = this.token;
    this.reset();
    return token;
  }

  reset(): void {
    this.token = null;
    if (this.widgetId !== null && typeof window.turnstile?.reset === "function") {
      window.turnstile.reset(this.widgetId);
    }
  }
}
