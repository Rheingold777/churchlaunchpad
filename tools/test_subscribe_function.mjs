import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import test, { afterEach } from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const functionSource = readFileSync(join(root, "functions", "api", "subscribe.js"), "utf8");
const functionModuleUrl = `data:text/javascript;base64,${Buffer.from(functionSource).toString("base64")}`;
const { onRequestPost } = await import(functionModuleUrl);
const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function request(body, headers = {}) {
  return new Request("https://churchlaunchpad.org/api/subscribe", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

test("Beehiiv is absent and every newsletter CTA stays on the managed site", () => {
  const htmlFiles = [
    "index.html",
    "privacy.html",
    ...readdirSync(join(root, "posts"))
      .filter((name) => name.endsWith(".html"))
      .map((name) => join("posts", name)),
  ];

  for (const relativePath of htmlFiles) {
    const source = readFileSync(join(root, relativePath), "utf8");
    assert.doesNotMatch(source, /beehiiv\.com/i, relativePath);
  }

  const datedPosts = htmlFiles.filter((name) => name.startsWith(join("posts", "2026-")));
  assert.equal(datedPosts.length, 8);
  for (const relativePath of datedPosts) {
    const source = readFileSync(join(root, relativePath), "utf8");
    assert.match(source, /href="\/#newsletter"[^>]*>Subscribe Free/);
  }

  const homepage = readFileSync(join(root, "index.html"), "utf8");
  assert.match(homepage, /id="newsletter"/);
  assert.match(homepage, /fetch\('\/api\/subscribe'/);
  assert.match(readFileSync(join(root, "privacy.html"), "utf8"), /Buttondown/);
});

test("honeypot succeeds without contacting Buttondown", async () => {
  globalThis.fetch = async () => {
    throw new Error("upstream should not be called");
  };
  const response = await onRequestPost({
    request: request({ email: "bot@example.com", website: "filled" }),
    env: {},
  });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
});

test("missing server-side key fails closed", async () => {
  const response = await onRequestPost({
    request: request({ email: "person@example.com", website: "" }),
    env: {},
  });
  assert.equal(response.status, 500);
  assert.equal((await response.json()).ok, false);
});

test("invalid email is rejected without an upstream call", async () => {
  globalThis.fetch = async () => {
    throw new Error("upstream should not be called");
  };
  const response = await onRequestPost({
    request: request({ email: "not-an-email", website: "" }),
    env: { BUTTONDOWN_API_KEY: "test-key" },
  });
  assert.equal(response.status, 400);
});

test("valid signup uses Buttondown server-side and preserves double opt-in", async () => {
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response("{}", { status: 201 });
  };

  const response = await onRequestPost({
    request: request(
      { email: " Person@Example.com ", website: "" },
      { referer: "https://churchlaunchpad.org/posts/example", "cf-connecting-ip": "192.0.2.1" },
    ),
    env: { BUTTONDOWN_API_KEY: "test-key" },
  });
  const payload = JSON.parse(captured.options.body);

  assert.equal(response.status, 200);
  assert.equal(captured.url, "https://api.buttondown.com/v1/subscribers");
  assert.equal(captured.options.headers.Authorization, "Token test-key");
  assert.deepEqual(payload, {
    email_address: "person@example.com",
    referrer_url: "https://churchlaunchpad.org/posts/example",
    ip_address: "192.0.2.1",
  });
  assert.equal("type" in payload, false, "Buttondown double opt-in must remain enabled");
  assert.deepEqual(await response.json(), { ok: true });
});

test("untrusted referrer is replaced with the canonical site", async () => {
  let capturedPayload;
  globalThis.fetch = async (_url, options) => {
    capturedPayload = JSON.parse(options.body);
    return new Response("{}", { status: 201 });
  };
  await onRequestPost({
    request: request(
      { email: "person@example.com", website: "" },
      { referer: "https://untrusted.example/phishing" },
    ),
    env: { BUTTONDOWN_API_KEY: "test-key" },
  });
  assert.equal(capturedPayload.referrer_url, "https://churchlaunchpad.org/");
});

test("legacy duplicate response remains a successful idempotent signup", async () => {
  globalThis.fetch = async () => new Response("Subscriber already exists", { status: 400 });
  const response = await onRequestPost({
    request: request({ email: "person@example.com", website: "" }),
    env: { BUTTONDOWN_API_KEY: "test-key" },
  });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, alreadySubscribed: true });
});

test("upstream failures return a sanitized gateway error", async () => {
  globalThis.fetch = async () => new Response("internal details", { status: 500 });
  const response = await onRequestPost({
    request: request({ email: "person@example.com", website: "" }),
    env: { BUTTONDOWN_API_KEY: "test-key" },
  });
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), {
    ok: false,
    error: "Signup did not go through. Please try again.",
  });
});
