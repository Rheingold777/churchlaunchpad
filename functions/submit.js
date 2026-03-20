// Cloudflare Pages Function - handles form submissions
export async function onRequestPost(context) {
  const AIRTABLE_TOKEN = context.env.AIRTABLE_TOKEN;
  const BASE_ID = 'app3HmxmQ5lk8PAMo';
  const TABLE_ID = 'tblOMT6A8c1LYfO0d';
  
  try {
    const body = await context.request.json();
    
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
    
    const response = await fetch(`https://api.airtable.com/v0/${BASE_ID}/${TABLE_ID}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${AIRTABLE_TOKEN}`
      },
      body: JSON.stringify(airtableData)
    });
    
    if (!response.ok) {
      throw new Error('Airtable submission failed');
    }
    
    return new Response(JSON.stringify({ success: true }), {
      headers: { 'Content-Type': 'application/json' }
    });
    
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
