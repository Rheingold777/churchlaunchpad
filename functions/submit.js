// Cloudflare Pages Function - handles form submissions
export async function onRequestPost(context) {
  const AIRTABLE_TOKEN = context.env.AIRTABLE_TOKEN;
  const RESEND_API_KEY = context.env.RESEND_API_KEY;
  const BASE_ID = 'app3HmxmQ5lk8PAMo';
  const TABLE_ID = 'tblOMT6A8c1LYfO0d';
  
  try {
    const body = await context.request.json();
    
    // 1. Save to Airtable
    const airtableData = {
      fields: {
        "Name": body.contactName,
        "Organization": body.churchName,
        "Email": body.email,
        "Interested In": ["ChurchLaunchpad"],
        "Status": "New",
        "Source": "Website",
        "Notes": `Biggest challenge: ${body.biggestChallenge || 'Not specified'}\nSubmitted: ${new Date().toISOString()}`
      }
    };
    
    const airtableResponse = await fetch(`https://api.airtable.com/v0/${BASE_ID}/${TABLE_ID}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${AIRTABLE_TOKEN}`
      },
      body: JSON.stringify(airtableData)
    });
    
    if (!airtableResponse.ok) {
      console.error('Airtable error:', await airtableResponse.text());
    }
    
    // 2. Send welcome email via Resend
    const emailHtml = `
<!DOCTYPE html>
<html>
<head>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }
    .content { background: #f9fafb; padding: 30px; border-radius: 0 0 8px 8px; }
    .highlight { background: #fff; padding: 20px; border-left: 4px solid #f59e0b; margin: 20px 0; }
    .cta { display: inline-block; background: #f59e0b; color: #1e3a5f; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 20px 0; }
    .footer { text-align: center; color: #666; font-size: 14px; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1 style="margin: 0;">🚀 Welcome to ChurchLaunchpad!</h1>
    </div>
    <div class="content">
      <p>Hi ${body.contactName},</p>
      
      <p>Thank you for your interest in ChurchLaunchpad! We're excited to help <strong>${body.churchName}</strong> grow its digital presence.</p>
      
      <div class="highlight">
        <strong>What happens next?</strong>
        <p style="margin-bottom: 0;">Within 24 hours, you'll receive a detailed digital presence assessment for your church — completely free, no strings attached.</p>
      </div>
      
      <p>In the meantime, here's what we'll be looking at:</p>
      <ul>
        <li>✅ Website effectiveness & mobile experience</li>
        <li>✅ Social media presence & engagement</li>
        <li>✅ Google Business Profile optimization</li>
        <li>✅ Online visitor experience</li>
        <li>✅ Specific recommendations for ${body.churchName}</li>
      </ul>
      
      <p>Questions? Just reply to this email — we read every message.</p>
      
      <p>Blessings,<br>
      <strong>The ChurchLaunchpad Team</strong></p>
    </div>
    <div class="footer">
      <p>ChurchLaunchpad — Helping churches launch into the digital age</p>
    </div>
  </div>
</body>
</html>`;

    const emailResponse = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RESEND_API_KEY}`
      },
      body: JSON.stringify({
        from: 'ChurchLaunchpad <hello@churchlaunchpad.org>',
        to: body.email,
        subject: `Welcome ${body.contactName}! Your free church assessment is on the way`,
        html: emailHtml
      })
    });
    
    if (!emailResponse.ok) {
      console.error('Resend error:', await emailResponse.text());
    }
    
    // 3. Notify Discord #biz-ops via webhook
    const DISCORD_WEBHOOK = context.env.DISCORD_WEBHOOK;
    if (DISCORD_WEBHOOK) {
      const discordEmbed = {
        embeds: [{
          title: "🚀 New ChurchLaunchpad Lead!",
          color: 0xf59e0b,
          fields: [
            { name: "Contact", value: body.contactName, inline: true },
            { name: "Church", value: body.churchName, inline: true },
            { name: "Email", value: body.email, inline: false },
            { name: "Challenge", value: body.biggestChallenge || "Not specified", inline: false }
          ],
          timestamp: new Date().toISOString(),
          footer: { text: "ChurchLaunchpad Lead Capture" }
        }]
      };
      
      await fetch(DISCORD_WEBHOOK, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(discordEmbed)
      }).catch(err => console.error('Discord error:', err));
    }
    
    return new Response(JSON.stringify({ success: true }), {
      headers: { 'Content-Type': 'application/json' }
    });
    
  } catch (error) {
    console.error('Submit error:', error);
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
