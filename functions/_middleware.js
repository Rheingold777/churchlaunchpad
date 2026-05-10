const HELD_EXACT_PATHS = new Set([
  "/audit",
  "/audit.html",
  "/rss.xml",
  "/posts/google-reviews",
  "/posts/google-reviews.html",
  "/posts/2026-04-29-google-review-policy-lobby-ban",
  "/posts/2026-04-29-google-review-policy-lobby-ban.html",
]);

function isHeldPath(pathname) {
  if (HELD_EXACT_PATHS.has(pathname)) {
    return true;
  }

  return /^\/images\/testimonial-[^/]+\.png$/i.test(pathname);
}

export async function onRequest(context) {
  const url = new URL(context.request.url);

  if (isHeldPath(url.pathname)) {
    return new Response("Not found", {
      status: 404,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex, nofollow",
      },
    });
  }

  return context.next();
}
