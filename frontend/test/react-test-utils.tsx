import { JSDOM } from "jsdom";
import type { ReactNode } from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";

type RenderHandle = {
  container: HTMLDivElement;
  rerender: (node: ReactNode) => Promise<void>;
  unmount: () => Promise<void>;
};

type SavedGlobals = {
  window?: typeof globalThis.window;
  self?: typeof globalThis.self;
  document?: typeof globalThis.document;
  navigator?: typeof globalThis.navigator;
  localStorage?: typeof globalThis.localStorage;
  sessionStorage?: typeof globalThis.sessionStorage;
  HTMLElement?: typeof globalThis.HTMLElement;
  Node?: typeof globalThis.Node;
  Event?: typeof globalThis.Event;
  MouseEvent?: typeof globalThis.MouseEvent;
  CustomEvent?: typeof globalThis.CustomEvent;
  MutationObserver?: typeof globalThis.MutationObserver;
  getComputedStyle?: typeof globalThis.getComputedStyle;
  requestAnimationFrame?: typeof globalThis.requestAnimationFrame;
  cancelAnimationFrame?: typeof globalThis.cancelAnimationFrame;
  atob?: typeof globalThis.atob;
  btoa?: typeof globalThis.btoa;
  IS_REACT_ACT_ENVIRONMENT?: boolean;
};

function setGlobal<K extends keyof SavedGlobals>(key: K, value: SavedGlobals[K]): void {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    writable: true,
    value,
  });
}

export function installDom(url = "https://carapace.example.test/"): () => void {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url });
  const saved: SavedGlobals = {
    window: globalThis.window,
    self: globalThis.self,
    document: globalThis.document,
    navigator: globalThis.navigator,
    localStorage: globalThis.localStorage,
    sessionStorage: globalThis.sessionStorage,
    HTMLElement: globalThis.HTMLElement,
    Node: globalThis.Node,
    Event: globalThis.Event,
    MouseEvent: globalThis.MouseEvent,
    CustomEvent: globalThis.CustomEvent,
    MutationObserver: globalThis.MutationObserver,
    getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
    cancelAnimationFrame: globalThis.cancelAnimationFrame,
    atob: globalThis.atob,
    btoa: globalThis.btoa,
    IS_REACT_ACT_ENVIRONMENT: (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT,
  };

  setGlobal("window", dom.window as unknown as typeof globalThis.window);
  setGlobal("self", dom.window as unknown as typeof globalThis.self);
  setGlobal("document", dom.window.document as typeof globalThis.document);
  setGlobal("navigator", dom.window.navigator as typeof globalThis.navigator);
  setGlobal("localStorage", dom.window.localStorage as typeof globalThis.localStorage);
  setGlobal("sessionStorage", dom.window.sessionStorage as typeof globalThis.sessionStorage);
  setGlobal("HTMLElement", dom.window.HTMLElement as typeof globalThis.HTMLElement);
  setGlobal("Node", dom.window.Node as typeof globalThis.Node);
  setGlobal("Event", dom.window.Event as typeof globalThis.Event);
  setGlobal("MouseEvent", dom.window.MouseEvent as typeof globalThis.MouseEvent);
  setGlobal("CustomEvent", dom.window.CustomEvent as typeof globalThis.CustomEvent);
  setGlobal(
    "MutationObserver",
    dom.window.MutationObserver as typeof globalThis.MutationObserver,
  );
  setGlobal(
    "getComputedStyle",
    dom.window.getComputedStyle.bind(dom.window) as typeof globalThis.getComputedStyle,
  );
  setGlobal(
    "requestAnimationFrame",
    ((callback: FrameRequestCallback) => setTimeout(callback, 0)) as typeof globalThis.requestAnimationFrame,
  );
  setGlobal(
    "cancelAnimationFrame",
    ((handle: number) => clearTimeout(handle)) as typeof globalThis.cancelAnimationFrame,
  );
  setGlobal("atob", dom.window.atob.bind(dom.window) as typeof globalThis.atob);
  setGlobal("btoa", dom.window.btoa.bind(dom.window) as typeof globalThis.btoa);
  Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", {
    configurable: true,
    writable: true,
    value: true,
  });

  return () => {
    const keys = Object.entries(saved) as Array<[keyof SavedGlobals, SavedGlobals[keyof SavedGlobals]]>;
    for (const [key, value] of keys) {
      if (value === undefined) {
        delete (globalThis as Record<string, unknown>)[key];
      } else {
        setGlobal(key, value);
      }
    }
    dom.window.close();
  };
}

export async function renderReact(node: ReactNode): Promise<RenderHandle> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(node);
  });

  return {
    container,
    async rerender(nextNode: ReactNode): Promise<void> {
      await act(async () => {
        root.render(nextNode);
      });
    },
    async unmount(): Promise<void> {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

export async function flushReact(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

export async function click(element: Element): Promise<void> {
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

export async function setInputValue(
  element: HTMLInputElement,
  value: string,
): Promise<void> {
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new window.Event("input", { bubbles: true }));
    element.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
}

export async function setCheckboxValue(
  element: HTMLInputElement,
  checked: boolean,
): Promise<void> {
  await act(async () => {
    element.checked = checked;
    element.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
}

export async function dispatchWindowEvent(event: Event): Promise<void> {
  await act(async () => {
    window.dispatchEvent(event);
  });
}

export async function dispatchDocumentEvent(event: Event): Promise<void> {
  await act(async () => {
    document.dispatchEvent(event);
  });
}

export async function runInAct(callback: () => void | Promise<void>): Promise<void> {
  await act(async () => {
    await callback();
  });
}
