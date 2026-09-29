import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TurnstileController } from "@/lib/turnstile";

const render = vi.fn(() => "w-1");
const reset = vi.fn();
const remove = vi.fn();
const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

const SCRIPT_SELECTOR = 'script[src^="https://challenges.cloudflare.com/turnstile/v0/api.js"]';

beforeEach(() => {
  vi.stubGlobal("window", {
    ...window,
    turnstile: { render, reset, remove },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  document.querySelectorAll(SCRIPT_SELECTOR).forEach((s) => s.remove());
});

describe("TurnstileController", () => {
  it("renderiza o widget e fica 'pending' até o token chegar", async () => {
    const ctl = new TurnstileController();
    const box = document.createElement("div");
    await ctl.render(box, "site-key");
    expect(render).toHaveBeenCalledOnce();
    expect(ctl.status).toBe("pending");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    expect(ctl.status).toBe("ready");
    expect(ctl.token).toBe("tok-1");
  });

  it("consume o token e reseta — token é de uso único", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    expect(ctl.consume()).toEqual({ ok: true, token: "tok-1" });
    expect(reset).toHaveBeenCalledWith("w-1");
    expect(ctl.token).toBeNull();
  });

  it("segundo consume falha até novo token", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    ctl.consume();
    expect(ctl.consume()).toEqual({ ok: false, reason: "sem token" });
  });

  it("token vazio nunca é enviado", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("");
    expect(ctl.consume()).toEqual({ ok: false, reason: "sem token" });
  });

  it("expired-callback limpa o token e volta a 'idle'", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const opts = render.mock.calls[0][1];
    opts.callback("tok-1");
    opts["expired-callback"]();
    expect(ctl.token).toBeNull();
    expect(ctl.status).toBe("idle");
  });

  it("error-callback limpa o token e marca 'error'", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const opts = render.mock.calls[0][1];
    opts.callback("tok-1");
    opts["error-callback"]();
    expect(ctl.token).toBeNull();
    expect(ctl.status).toBe("error");
  });

  it("reset com widget montado volta a 'pending'", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const opts = render.mock.calls[0][1];
    opts.callback("tok-1");
    ctl.reset();
    expect(reset).toHaveBeenCalledWith("w-1");
    expect(ctl.token).toBeNull();
    expect(ctl.status).toBe("pending");
  });

  it("reset sem widget montado volta a 'idle'", () => {
    const ctl = new TurnstileController();
    ctl.status = "error";
    ctl.reset();
    expect(ctl.status).toBe("idle");
  });

  it("destroy remove o widget e limpa o estado", async () => {
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    const opts = render.mock.calls[0][1];
    opts.callback("tok-1");
    ctl.destroy();
    expect(remove).toHaveBeenCalledWith("w-1");
    expect(ctl.widgetId).toBeNull();
    expect(ctl.token).toBeNull();
    expect(ctl.status).toBe("idle");
  });

  it("render de novo remove o widget anterior antes de criar outro", async () => {
    const ctl = new TurnstileController();
    const box = document.createElement("div");
    await ctl.render(box, "site-key");
    await ctl.render(box, "site-key");
    expect(remove).toHaveBeenCalledOnce();
    expect(remove).toHaveBeenCalledWith("w-1");
    expect(render).toHaveBeenCalledTimes(2);
    expect(ctl.status).toBe("pending");
  });

  it("render que lança exceção vira 'unavailable'", async () => {
    render.mockImplementationOnce(() => {
      throw new Error("widget explodiu");
    });
    const ctl = new TurnstileController();
    await ctl.render(document.createElement("div"), "site-key");
    expect(ctl.status).toBe("unavailable");
    expect(consoleError).toHaveBeenCalled();
    expect(ctl.consume()).toEqual({ ok: false, reason: "indisponível" });
  });

  it("não trava em 'unavailable' enquanto o script carrega", async () => {
    vi.stubGlobal("window", {});
    const ctl = new TurnstileController();
    const p = ctl.render(document.createElement("div"), "site-key");
    expect(ctl.status).toBe("idle");
    vi.stubGlobal("window", { turnstile: { render, reset, remove } });
    document.querySelector<HTMLScriptElement>(SCRIPT_SELECTOR)?.dispatchEvent(new Event("load"));
    await p;
    expect(render).toHaveBeenCalledOnce();
    expect(ctl.status).toBe("pending");
  });

  it("marca 'unavailable' quando o script é bloqueado", async () => {
    vi.stubGlobal("window", {});
    const ctl = new TurnstileController();
    const p = ctl.render(document.createElement("div"), "site-key");
    expect(ctl.status).not.toBe("unavailable");
    document.querySelector<HTMLScriptElement>(SCRIPT_SELECTOR)?.dispatchEvent(new Event("error"));
    await p;
    expect(ctl.status).toBe("unavailable");
    expect(ctl.consume()).toEqual({ ok: false, reason: "indisponível" });
  });
});

describe("loadTurnstile", () => {
  it("resolve na hora quando window.turnstile já está pronto", async () => {
    vi.resetModules();
    const { loadTurnstile } = await import("@/lib/turnstile");
    await expect(loadTurnstile()).resolves.toBeUndefined();
    expect(document.querySelector(SCRIPT_SELECTOR)).toBeNull();
  });

  it("injeta o script uma única vez e compartilha o mesmo promise", async () => {
    vi.stubGlobal("window", {});
    vi.resetModules();
    const { loadTurnstile } = await import("@/lib/turnstile");
    const p1 = loadTurnstile();
    const p2 = loadTurnstile();
    expect(p1).toBe(p2);
    expect(document.querySelectorAll(SCRIPT_SELECTOR)).toHaveLength(1);
    document.querySelector<HTMLScriptElement>(SCRIPT_SELECTOR)?.dispatchEvent(new Event("error"));
    await expect(p1).rejects.toThrow();
  });

  it("reaproveita script já existente no DOM", async () => {
    vi.stubGlobal("window", {});
    const existing = document.createElement("script");
    existing.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    document.head.appendChild(existing);
    vi.resetModules();
    const { loadTurnstile } = await import("@/lib/turnstile");
    const p = loadTurnstile();
    expect(document.querySelectorAll(SCRIPT_SELECTOR)).toHaveLength(1);
    vi.stubGlobal("window", { turnstile: { render, reset, remove } });
    existing.dispatchEvent(new Event("load"));
    await expect(p).resolves.toBeUndefined();
  });
});
