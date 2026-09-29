import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TurnstileController } from "@/lib/turnstile";

const render = vi.fn(() => "w-1");
const reset = vi.fn();

beforeEach(() => {
  vi.stubGlobal("window", {
    ...window,
    turnstile: { render, reset },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("TurnstileController", () => {
  it("renderiza e captura o token", () => {
    const ctl = new TurnstileController();
    const box = document.createElement("div");
    ctl.render(box, "site-key");
    expect(render).toHaveBeenCalledOnce();
    expect(ctl.status).toBe("ready");
  });

  it("consume o token e reseta — token é de uso único", () => {
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    expect(ctl.consume()).toBe("tok-1");
    expect(reset).toHaveBeenCalledWith("w-1");
    expect(ctl.token).toBeNull();
  });

  it("segundo consume devolve null até novo token", () => {
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    ctl.consume();
    expect(ctl.consume()).toBeNull();
  });

  it("marca indisponível sem window.turnstile", () => {
    vi.stubGlobal("window", {});
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    expect(ctl.status).toBe("unavailable");
    expect(ctl.consume()).toBeNull();
  });

  it("expired-callback limpa o token", () => {
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    const opts = render.mock.calls[0][1];
    opts.callback("tok-1");
    opts["expired-callback"]();
    expect(ctl.token).toBeNull();
  });
});
