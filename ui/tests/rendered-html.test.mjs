import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render(pathname = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${pathname}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${pathname}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the finished control center", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Aerium Control — CrazySwarm<\/title>/i);
  assert.match(html, /AERIUM/);
  assert.match(html, /aria-label="Mission controls"/);
  assert.match(html, />Mission</);
  assert.match(html, /No room/);
  assert.doesNotMatch(html, /READY TO RUN|Telemetry and evidence|Choose a mission|STARTING/);
  assert.doesNotMatch(html, /fixture-sim01|99\.4%|physical radio/i);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("ships deterministic operator-state fixtures", async () => {
  const response = await render("/fixtures");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Operator-state fixtures/);
  assert.match(html, /TEST FIXTURES — NOT TELEMETRY/);
  assert.match(html, /Loading/);
  assert.match(html, /Disconnected/);
  assert.match(html, /Permission denied/);
  assert.match(html, /symbol and text, never color alone/i);
});

test("has no disposable starter preview or starter SVG assets", async () => {
  const packageJson = await readFile(new URL("../package.json", import.meta.url), "utf8");
  assert.doesNotMatch(packageJson, /react-loading-skeleton|drizzle/);
  await assert.rejects(access(new URL("../app/_sites-preview", import.meta.url)));
  for (const name of ["favicon.svg", "file.svg", "globe.svg", "window.svg"]) {
    await assert.rejects(access(new URL(`../public/${name}`, import.meta.url)));
  }
});
