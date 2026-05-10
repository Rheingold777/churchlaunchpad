const DEFAULT_ACCOUNTS_HOST = "https://accounts.zoho.com";
const DEFAULT_MAIL_HOST = "https://mail.zoho.com";
const TARGET_EMAIL = "hello@churchlaunchpad.org";

function response(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function redirectToThanks(request) {
  const url = new URL(request.url);
  url.pathname = "/";
  url.search = "?submitted=true";
  return Response.redirect(url.toString(), 303);
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

async function readSubmission(request) {
  const contentType = request.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    const body = await request.json();
    return {
      churchName: body.church_name || body.churchName,
      pastorName: body.pastor_name || body.pastorName || body.name,
      email: body.email,
      location: body.location,
      services: Array.isArray(body.services) ? body.services : [body.services].filter(Boolean),
      website: body.website,
    };
  }

  const form = await request.formData();
  return {
    churchName: form.get("church_name"),
    pastorName: form.get("pastor_name"),
    email: form.get("email"),
    location: form.get("location"),
    services: form.getAll("services[]"),
    website: form.get("website"),
  };
}

async function getZohoAccessToken(env) {
  const required = ["ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"];
  for (const name of required) {
    if (!env[name]) {
      throw new Error("Zoho mail is not configured.");
    }
  }

  const body = new URLSearchParams({
    refresh_token: env.ZOHO_REFRESH_TOKEN,
    client_id: env.ZOHO_CLIENT_ID,
    client_secret: env.ZOHO_CLIENT_SECRET,
    grant_type: "refresh_token",
  });

  const tokenResponse = await fetch(`${env.ZOHO_ACCOUNTS_HOST || DEFAULT_ACCOUNTS_HOST}/oauth/v2/token`, {
    method: "POST",
    body,
  });
  const tokenData = await tokenResponse.json().catch(() => ({}));

  if (!tokenResponse.ok || !tokenData.access_token) {
    throw new Error("Zoho token refresh failed.");
  }

  return tokenData.access_token;
}

function buildEmailHtml(submission) {
  const services = submission.services.length ? submission.services.join(", ") : "Not specified";

  return `
    <h2>New ChurchLaunchPad assessment request</h2>
    <table cellpadding="8" cellspacing="0" style="border-collapse: collapse; font-family: Arial, sans-serif;">
      <tr><td><strong>Church</strong></td><td>${escapeHtml(submission.churchName)}</td></tr>
      <tr><td><strong>Name</strong></td><td>${escapeHtml(submission.pastorName)}</td></tr>
      <tr><td><strong>Email</strong></td><td>${escapeHtml(submission.email)}</td></tr>
      <tr><td><strong>Location</strong></td><td>${escapeHtml(submission.location)}</td></tr>
      <tr><td><strong>Help requested</strong></td><td>${escapeHtml(services)}</td></tr>
      <tr><td><strong>Submitted</strong></td><td>${escapeHtml(new Date().toISOString())}</td></tr>
    </table>
  `;
}

async function sendZohoMail(env, submission) {
  if (!env.ZOHO_ACCOUNT_ID) {
    throw new Error("Zoho account is not configured.");
  }

  const token = await getZohoAccessToken(env);
  const mailHost = env.ZOHO_MAIL_HOST || DEFAULT_MAIL_HOST;
  const subject = `ChurchLaunchPad assessment request - ${submission.churchName}`;
  const payload = {
    fromAddress: TARGET_EMAIL,
    toAddress: TARGET_EMAIL,
    subject,
    content: buildEmailHtml(submission),
    mailFormat: "html",
  };

  const mailResponse = await fetch(`${mailHost}/api/accounts/${env.ZOHO_ACCOUNT_ID}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Zoho-oauthtoken ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!mailResponse.ok) {
    throw new Error("Zoho mail send failed.");
  }
}

export async function onRequestPost({ request, env }) {
  let submission;
  try {
    submission = await readSubmission(request);
  } catch {
    return response({ ok: false, error: "Could not read the form." }, 400);
  }

  if (submission.website) {
    return redirectToThanks(request);
  }

  submission = {
    churchName: String(submission.churchName || "").trim(),
    pastorName: String(submission.pastorName || "").trim(),
    email: String(submission.email || "").trim().toLowerCase(),
    location: String(submission.location || "").trim(),
    services: submission.services.map((service) => String(service || "").trim()).filter(Boolean),
  };

  if (!submission.churchName || !submission.pastorName || !isValidEmail(submission.email) || !submission.location) {
    return response({ ok: false, error: "Missing required form fields." }, 400);
  }

  try {
    await sendZohoMail(env, submission);
    return redirectToThanks(request);
  } catch (error) {
    console.error("Assessment submit failed", error);
    return response({ ok: false, error: "Assessment request did not go through." }, 502);
  }
}
