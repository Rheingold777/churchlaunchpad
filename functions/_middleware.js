const HELD_EXACT_PATHS = new Set([
  "/audit",
  "/audit.html",
  "/rss.xml",
  "/posts/2026-04-29-google-review-policy-lobby-ban",
  "/posts/2026-04-29-google-review-policy-lobby-ban.html",
]);

const SECURITY_HEADERS = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "SAMEORIGIN",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
};

function isHeldPath(pathname) {
  return HELD_EXACT_PATHS.has(pathname);
}

function withSecurityHeaders(response) {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export async function onRequest(context) {
  const url = new URL(context.request.url);

  if (isHeldPath(url.pathname)) {
    return withSecurityHeaders(new Response("Not found", {
      status: 404,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex, nofollow",
      },
    }));
  }

  return withSecurityHeaders(await context.next());
}
