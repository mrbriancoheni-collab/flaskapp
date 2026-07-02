-- Update all existing email sequence step-1 rows to use the new subject/body
-- that promotes the $499 lifetime plan and removes {{decision_maker_name}}.
-- Only touches rows whose subject still matches the old default (or the previous
-- interim version), so custom/manually-written sequences are left alone.

UPDATE email_sequences
SET
    subject   = 'Are your Google Ads actually booking jobs in {{location}}?',
    body_text = 'Hi there,

I came across {{company_name}} while looking at {{service_type}} businesses running Google Ads in {{location}}.

Most {{service_type}} companies I talk to are spending $1,500–$5,000/month on Google Ads without a clear picture of which campaigns are actually booking jobs — versus burning money on clicks that never convert.

FieldSprout connects directly to your Google Ads account and shows you:

- Which campaigns and keywords are generating real calls and booked jobs
- Where your budget is being wasted on irrelevant searches
- Your cost per booked job — updated daily

We have a lifetime deal running right now: $499 one-time for a single location, no monthly fees. Most clients recover that in wasted ad spend within the first 30 days.

See the deal and connect your account here:
https://fieldsprout.io/lifetime/499

Worth seeing if it pays for itself in your first month?

Brian
FieldSprout
https://fieldsprout.io

---
Reply "unsubscribe" to opt out.',
    body_html = 'Hi there,<br><br>I came across {{company_name}} while looking at {{service_type}} businesses running Google Ads in {{location}}.<br><br>Most {{service_type}} companies I talk to are spending $1,500–$5,000/month on Google Ads without a clear picture of which campaigns are actually booking jobs — versus burning money on clicks that never convert.<br><br>FieldSprout connects directly to your Google Ads account and shows you:<br><br>- Which campaigns and keywords are generating real calls and booked jobs<br>- Where your budget is being wasted on irrelevant searches<br>- Your cost per booked job — updated daily<br><br>We have a lifetime deal running right now: $499 one-time for a single location, no monthly fees. Most clients recover that in wasted ad spend within the first 30 days.<br><br>See the deal and connect your account here:<br><a href="https://fieldsprout.io/lifetime/499">https://fieldsprout.io/lifetime/499</a><br><br>Worth seeing if it pays for itself in your first month?<br><br>Brian<br>FieldSprout<br>https://fieldsprout.io<br><br>---<br>Reply "unsubscribe" to opt out.'
WHERE step_number = 1
  AND subject IN (
      'Quick question about {{company_name}}''s {{service_type}} services',
      'Are your Google Ads actually bringing in jobs, {{decision_maker_name}}?'
  );
