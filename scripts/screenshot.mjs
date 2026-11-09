#!/usr/bin/env node
// Capture light and dark screenshots of web UI pages with headless Chrome, logged in as the demo
// user. Talks to Chrome over the DevTools protocol with Node built-ins only (fetch, WebSocket), since
// the session cookie is HTTP-only and the Chrome command line alone cannot log in.
//
//   node scripts/screenshot.mjs [--base URL] [--out DIR] [--phone] NAME=PATH...
//
// Writes DIR/NAME-light.png and DIR/NAME-dark.png per page (NAME-phone-light.png with --phone).
// See "Screenshots" in docs/development.md.

import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseArgs } from "node:util";

const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
// Blink's preferredColorScheme setting: 0 is dark, 1 is light.
const SCHEMES = { light: 1, dark: 0 };
const DESKTOP = { width: 1280, height: 800, mobile: false };
const PHONE = { width: 390, height: 844, mobile: true };

const { values: options, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    base: { type: "string", default: "http://localhost:3000" },
    out: { type: "string", default: "screenshots" },
    user: { type: "string", default: "demo" },
    password: { type: "string", default: "carapace-demo" },
    // Time for data fetches and fonts to settle after the load event.
    settle: { type: "string", default: "3000" },
    phone: { type: "boolean", default: false },
  },
});
const pages = positionals.map((spec) => {
  const separator = spec.indexOf("=");
  const [name, path] = [spec.slice(0, separator), spec.slice(separator + 1)];
  if (!name || !path?.startsWith("/")) throw new Error(`Expected NAME=/path, got ${spec}`);
  return { name, path };
});
if (pages.length === 0) throw new Error("Pass at least one NAME=/path page");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function launchChrome(scheme) {
  const profile = mkdtempSync(join(tmpdir(), "carapace-shot-"));
  const chrome = spawn(CHROME, [
    "--headless=new",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    `--blink-settings=preferredColorScheme=${SCHEMES[scheme]}`,
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ]);
  const port = await new Promise((resolve, reject) => {
    let stderr = "";
    chrome.stderr.on("data", (chunk) => {
      stderr += chunk;
      const match = stderr.match(/DevTools listening on ws:\/\/[^:]+:(\d+)\//);
      if (match) resolve(match[1]);
    });
    chrome.on("exit", (code) => reject(new Error(`Chrome exited with ${code}:\n${stderr}`)));
  });
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((target) => target.type === "page");
  return {
    page: await connect(page.webSocketDebuggerUrl),
    async close() {
      chrome.kill();
      await once(chrome, "exit");
      rmSync(profile, { recursive: true, force: true, maxRetries: 5 });
    },
  };
}

async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let nextId = 0;
  const pending = new Map();
  const waiters = [];
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.id !== undefined) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    } else {
      for (const waiter of waiters.filter((w) => w.method === message.method)) {
        waiters.splice(waiters.indexOf(waiter), 1);
        waiter.resolve(message.params);
      }
    }
  };
  return {
    send(method, params = {}) {
      const id = ++nextId;
      socket.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    once(method) {
      return new Promise((resolve) => waiters.push({ method, resolve }));
    },
  };
}

async function navigate(page, url) {
  const loaded = page.once("Page.loadEventFired");
  await page.send("Page.navigate", { url });
  await loaded;
}

async function evaluate(page, expression) {
  const { result, exceptionDetails } = await page.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? exceptionDetails.text);
  return result.value;
}

async function logIn(page) {
  await navigate(page, options.base);
  const credentials = JSON.stringify({ username: options.user, password: options.password });
  const status = await evaluate(
    page,
    `fetch("/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json"},
      body: ${JSON.stringify(credentials)}}).then((r) => r.status)`,
  );
  if (status !== 200) throw new Error(`Login as ${options.user} failed with HTTP ${status}`);
  // The frontend treats a stored username as "connected"; the cookie carries the session. The UI
  // language follows the browser's languages unless overridden, and those come from the OS.
  await evaluate(
    page,
    `localStorage.setItem("carapace_username", ${JSON.stringify(options.user)});
     localStorage.setItem("carapace_locale_override", "en")`,
  );
}

async function capture(scheme) {
  const chrome = await launchChrome(scheme);
  try {
    const { page } = chrome;
    await page.send("Page.enable");
    const viewport = options.phone ? PHONE : DESKTOP;
    await page.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 2 });
    // Fixed language and time zone, so pictures don't depend on the machine taking them.
    await page.send("Emulation.setLocaleOverride", { locale: "en-US" });
    await page.send("Emulation.setTimezoneOverride", { timezoneId: "UTC" });
    await logIn(page);
    for (const { name, path } of pages) {
      await navigate(page, new URL(path, options.base).href);
      await sleep(Number(options.settle));
      // The Next.js dev indicator is not part of the UI.
      await evaluate(
        page,
        `document.head.insertAdjacentHTML("beforeend", "<style>nextjs-portal{display:none!important}</style>")`,
      );
      const { data } = await page.send("Page.captureScreenshot", { format: "png" });
      const file = join(options.out, `${name}${options.phone ? "-phone" : ""}-${scheme}.png`);
      writeFileSync(file, Buffer.from(data, "base64"));
      console.log(file);
    }
  } finally {
    await chrome.close();
  }
}

mkdirSync(options.out, { recursive: true });
for (const scheme of Object.keys(SCHEMES)) {
  await capture(scheme);
}
