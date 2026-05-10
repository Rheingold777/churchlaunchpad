const BUTTONDOWN_SUBSCRIBERS_URL = "https://api.buttondown.com/v1/subscribers";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

async function readPayload(request) {
  const contentType = request.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    return request.json();
  }

  const form = await request.formData();
  return Object.fromEntries(form.entries());
}

export async function onRequestPost({ request, env }) {
  if (!env.BUTTONDOWN_API_KEY) {
    return jsonResponse({ ok: false, error: "Newsletter is not configured yet." }, 500);
  }

  let payload;
  try {
    payload = await readPayload(request);
  } catch {
    return jsonResponse({ ok: false, error: "Could not read the signup." }, 400);
  }

  if (payload.website) {
    return jsonResponse({ ok: true });
  }

  const email = String(payload.email || payload.email_address || "").trim().toLowerCase();
  if (!isValidEmail(email)) {
    return jsonResponse({ ok: false, error: "Enter a valid email address." }, 400);
  }

  const referrer = request.headers.get("referer") || "https://churchlaunchpad.org/";
  const ipAddress = request.headers.get("cf-connecting-ip") || undefined;
  const subscriber = {
    email_address: email,
    tags: ["churchlaunchpad", "website"],
    referrer_url: referrer,
    metadata: {
      brand: "ChurchLaunchPad",
      source: "website-footer",
    },
  };

  if (ipAddress) {
    subscriber.ip_address = ipAddress;
  }

  const response = await fetch(BUTTONDOWN_SUBSCRIBERS_URL, {
    method: "POST",
    headers: {
      Authorization: `Token ${env.BUTTONDOWN_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(subscriber),
  });

  if (response.ok) {
    return jsonResponse({ ok: true });
  }

  const text = await response.text();
  const alreadySubscribed =
    response.status === 400 &&
    /already|duplicate|exists|subscribed/i.test(text);

  if (alreadySubscribed) {
    return jsonResponse({ ok: true, alreadySubscribed: true });
  }

  return jsonResponse({ ok: false, error: "Signup did not go through. Please try again." }, 502);
}

export async function onRequestOptions() {
  return jsonResponse({ ok: true });
}
