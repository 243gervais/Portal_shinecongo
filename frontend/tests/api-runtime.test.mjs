import test from "node:test";
import assert from "node:assert/strict";

globalThis.document = { getElementById: () => null, cookie: "csrftoken=test" };
globalThis.window = { location: { pathname: "/manager/", search: "", assign() {} } };
const { apiFetch, clearApiCache } = await import("../src/lib/api.js");
const json = (payload, status = 200) => new Response(JSON.stringify(payload), { status });

test("equivalent query orders and default page reuse one response", async () => {
  clearApiCache();
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return json({ rows: [1] }); };
  await apiFetch("/list/", { query: { site: "a", page: "1", status: "open" } });
  const result = await apiFetch("/list/", { query: { status: "open", site: "a" } });
  assert.deepEqual(result, { rows: [1] });
  assert.equal(calls, 1);
});

test("cancelled consumer does not cancel a shared navigation request", async () => {
  clearApiCache();
  let resolveFetch;
  let calls = 0;
  globalThis.fetch = () => { calls += 1; return new Promise(resolve => { resolveFetch = resolve; }); };
  const controller = new AbortController();
  const first = apiFetch("/shared/", { signal: controller.signal });
  const aborted = assert.rejects(first, { name: "AbortError" });
  const second = apiFetch("/shared/");
  controller.abort();
  resolveFetch(json({ ok: true }));
  await aborted;
  assert.deepEqual(await second, { ok: true });
  assert.equal(calls, 1);
});

test("slow reads abort and recover automatically with a fresh request", async () => {
  clearApiCache();
  const originalTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (callback, delay) => originalTimeout(callback, delay === 8_000 ? 1 : delay);
  let calls = 0;
  globalThis.fetch = async (_url, options) => {
    calls += 1;
    if (calls === 2) {
      assert.equal(options.cache, "reload");
      return json({ recovered: true });
    }
    return new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Timeout", "AbortError"))));
  };
  try {
    assert.deepEqual(await apiFetch("/slow/"), { recovered: true });
    assert.equal(calls, 2);
  } finally { globalThis.setTimeout = originalTimeout; }
});

test("writes are never automatically retried", async () => {
  clearApiCache();
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new TypeError("network"); };
  await assert.rejects(apiFetch("/save/", { method: "POST", data: {} }), /network/);
  assert.equal(calls, 1);
});

test("temporary gateway failures recover but permission failures are not retried", async () => {
  clearApiCache();
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return calls === 1 ? json({}, 503) : json({ ok: true }); };
  assert.deepEqual(await apiFetch("/gateway/"), { ok: true });
  assert.equal(calls, 2);
  calls = 0;
  globalThis.fetch = async () => { calls += 1; return json({ detail: "Forbidden" }, 403); };
  await assert.rejects(apiFetch("/private/"), { status: 403 });
  assert.equal(calls, 1);
});

test("persistent read timeouts stop after one retry", async () => {
  clearApiCache();
  const originalTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (callback, delay) => originalTimeout(callback, delay === 8_000 ? 1 : delay);
  let calls = 0;
  globalThis.fetch = async (_url, options) => {
    calls += 1;
    return new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Timeout", "AbortError"))));
  };
  try {
    await assert.rejects(apiFetch("/unavailable/"), /trop de temps/);
    assert.equal(calls, 2);
  } finally { globalThis.setTimeout = originalTimeout; }
});

test("a read started before a save cannot repopulate stale cache", async () => {
  clearApiCache();
  let resolveOld;
  let gets = 0;
  globalThis.fetch = async (_url, options) => {
    if (options.method === "POST") return json({ saved: true });
    gets += 1;
    if (gets === 1) return new Promise(resolve => { resolveOld = resolve; });
    return json({ value: "new" });
  };
  const old = apiFetch("/race/");
  await apiFetch("/save/", { method: "POST", data: {} });
  resolveOld(json({ value: "old" }));
  await old;
  assert.deepEqual(await apiFetch("/race/"), { value: "new" });
  assert.equal(gets, 2);
});
