# gridscout playbook

How to use gridscout to win a local business client, start to finish.

One rule that makes life simple: run everything through the venv Python so you
never think about which commands need the AI package.

```
.venv/bin/python -m gridscout.cli ...
```

Every command below uses that. The scan, heatmap, and history work without a key.
The analyze, report, and content commands call the API and cost a few cents.

---

## Once per terminal session

Load your keys:

```
cd ~/path/to/gridscout
source .env
```

That is it until you close the terminal.

---

## Per prospect, the sales flow

### 1. Get the business's location

Open Google Maps, right click the business's pin, and the first menu item is the
coordinates. Click to copy. First number is the latitude, second is the longitude.

### 2. Pick the keyword their customers actually type

Not their business name. What a customer searches: "hvac repair", "emergency
plumber", "roof repair near me". One keyword per scan.

### 3. Scan them

```
.venv/bin/python -m gridscout.cli scan \
  --business "Their Business Name" \
  --keyword "what customers search" \
  --lat 40.1514 --lng -82.9890 \
  --size 7 --radius 2 --provider dataforseo
```

Radius is the lever that frames the story:

- Dense area or a smaller business: `--radius 1.5` or `2`.
- Spread out or a strong, well known business: `--radius 3` to `5`.

If the first scan is all bright (they dominate) or almost all gray (tiny
footprint), re-scan with a different radius so the falloff fills the map. A 7x7
scan is about ten cents.

### 4. Show them the map, this is what sells

The scan writes an interactive heatmap to `output/`. Open the `.html` file. On a
call or a screen share, this is your moment:

- Bright pins are where they show up. Gray is where they are invisible.
- Use the competitor dropdown in the sidebar. Pick the competitor beating them
  and watch every pin flip to that competitor's ranks. That side by side is the
  "oh no" moment that books the call.

### 5. Build the pitch report

```
.venv/bin/python -m gridscout.cli analyze     # writes the pitch copy
.venv/bin/python -m gridscout.cli report      # builds the branded PDF
```

Both default to the most recent scan. The PDF lands in `output/` as
`<business>-<id>-report.pdf`. It shows the problem, the neighborhoods they are
losing, the competitors taking those calls, what it is costing them, and a call
to action pointing at your discovery-call booking link. It does not tell them how
to fix it. That is on purpose.

### 6. Send it and book the call

Email or hand over the PDF, or walk them through the heatmap live. The report ends
with your booking link, so the next step is a discovery call, not a DIY project.

---

## After they sign, fulfillment

Now you deliver the work. This is where the content command comes in. Keep it
internal until they are a client.

```
.venv/bin/python -m gridscout.cli content
```

It writes a folder to `output/<business>-<id>-content/`:

- a service-area page for each weak neighborhood,
- a Google Business Profile post per zone,
- the `LocalBusiness` schema snippet for their website,
- a competitor gap sheet.

These are drafts. Fill in the marked local details, then publish on their behalf.

---

## Keep the client, monthly

Re-scan the same business and keyword once a month, then:

```
.venv/bin/python -m gridscout.cli history \
  --business "Their Business Name" \
  --keyword "what customers search"
```

That shows visibility over time. When the edges push outward, you have proof the
retainer is working. That chart is what keeps them paying.

---

## What each command costs

- scan: about `size x size x $0.002`. A 7x7 is roughly ten cents (DataForSEO).
- analyze / report: a few cents each (Anthropic). Report reuses the cached
  analysis, so rebuilding the PDF is free.
- content: about ten cents (Anthropic).

A full prospect, scan plus pitch plus PDF, runs well under a quarter. Every run
prints its exact spend at the end.

---

## Handy flags

```
analyze 3            run against scan id 3 instead of the latest
--refresh            regenerate instead of using the cached AI output
--no-geo             skip the neighborhood name lookups (faster, offline)
```

To change your booking link or email on the report, edit `BOOKING_URL` and
`CONTACT_EMAIL` at the top of `gridscout/report.py`.
