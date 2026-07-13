"""The language layer. Python already did the arithmetic; this hands the findings
to Claude and asks for prose. It never asks the model to compute anything.

Separation of concerns is enforced here by what gets sent: the model receives the
findings file and is told, in the system prompt, that every number it writes must
come from that file. It is not given the raw scan or any tool to recompute one.

Missing key is a hard stop with directions, never a silent skip.
"""
import json
import os

DEFAULT_MODEL = "claude-sonnet-4-6"

# Per-model price in USD per 1M tokens: (input, output). Used to report real spend.
PRICES = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# The rules every model call in this tool runs under. This is the guardrail that
# keeps the copy honest and on-brand. It is deliberately blunt.
SYSTEM = """You are the writer for a tool that maps where a local business shows up on
Google Maps. You are handed a findings file: numbers a program already calculated from
a real scan. Your job is to turn those numbers into writing a busy small-business owner
will actually understand and act on.

Picture the reader: an HVAC contractor, a plumber, a dentist, a shop owner. Smart, busy,
runs a real business. Has never heard of SEO, ranking, grids, or scores, and does not
care to. Write like you are explaining it to them across the counter in plain English.

Hard rules, no exceptions:

1. Every number you state must come from the findings file. Never compute, estimate, or
   invent a rank, a competitor, a review count, a distance, or a gap. If the file does
   not contain a figure, do not state one.
2. Talk like a person, not a dashboard. Banned words and ideas, always translate them:
   - Never say "point", "points", "grid", "pin", "node", "coordinate", or "data point".
     We checked how they show up from many spots around their shop. Say it in terms of
     neighborhoods, streets, directions, and distance in miles.
   - Never give a decimal rank like "1.88" or say "average rank" or "position". Say
     "you show up first or second", "near the top", "on the first screen", or "buried
     where nobody looks".
   - Never say things like "top 3 at 44.9 percent of points". Say "across about half
     the area right around your shop, you are one of the first three businesses people
     see".
   - Do not lead with the visibility score. You may mention it once, late, only if you
     immediately explain it in plain words.
   - Do not use SEO jargon: no "prominence", "relevance", "local pack", "SERP",
     "citations", "signals", "optimize". If you mean Google trusting the business more,
     say that plainly.
3. Make the reach real and make it matter. Lead with how far from their shop they
   actually show up (the reach figures in the findings), and be honest that a short
   reach is a problem: everyone searching beyond it is finding a competitor instead.
   Frame it in customers and jobs, not metrics.
4. Never use em dashes. Use periods, commas, or the word "and".
5. Never use the words "free" or "snapshot".
6. Never claim a business can show up everywhere or beat every competitor across a whole
   city. How close the business physically is to the searcher is the biggest factor, and
   nothing beats that. What better reviews, photos, and profile work do is make Google
   more confident the business is real, active, and well liked, which stretches how far
   out it shows up, at the edges. That is the honest promise. Nothing bigger. Honor the
   honesty_constraint field.
7. Describe location with the real neighborhood names and directions in the findings.
8. Short sentences. No corporate filler, no "certainly", no hype. If the data does not
   support a claim, do not make it."""


def _require_key():
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set, so the analysis cannot run.\n\n"
            "  1. Go to https://console.anthropic.com/settings/keys\n"
            "  2. Create a key (starts with sk-ant-).\n"
            "  3. Add it to your .env file:  ANTHROPIC_API_KEY=\"sk-ant-...\"\n"
            "  4. Run:  source .env\n\n"
            "Then run the command again."
        )
    return key


def model_name():
    return os.getenv("GRIDSCOUT_MODEL") or DEFAULT_MODEL


def cost(model, usage):
    pin, pout = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return round(usage["input_tokens"] / 1e6 * pin
                 + usage["output_tokens"] / 1e6 * pout, 4)


def _client():
    _require_key()
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "The 'anthropic' package is not installed. From the project folder run:\n"
            "  .venv/bin/python -m pip install anthropic\n"
            "and run the AI commands with .venv/bin/python."
        )
    return anthropic.Anthropic()


def _sanitize(text):
    """Enforce the no-em-dash rule deterministically. The system prompt asks for
    it, but a rule this strict cannot be left to the model to remember, so we
    strip em and en dashes from every model response before it is ever saved. A
    spaced dash becomes a comma, a bare one a comma, an unspaced en dash a hyphen.
    """
    text = text.replace(" — ", ", ").replace(" – ", ", ")
    text = text.replace(" —", ",").replace(" –", ",")
    text = text.replace("— ", ", ").replace("– ", ", ")
    text = text.replace("—", ", ").replace("–", "-")
    return text


def _call(user_prompt, max_tokens):
    """One message to the model. Returns (text, usage dict)."""
    client = _client()
    model = model_name()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = _sanitize("".join(b.text for b in resp.content if b.type == "text"))
    usage = {"input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens}
    return text, usage, model


def write_analysis(findings):
    """The AI Ranking Coach writeup, in plain owner-facing language.

    Returns (markdown, usage, model)."""
    prompt = (
        "Here is the findings file for a scan of one business:\n\n"
        "```json\n" + json.dumps(findings, indent=2) + "\n```\n\n"
        "Write a short, plain-English report the owner will understand and act on. "
        "Follow every rule in your instructions, especially the plain-language ones. "
        "Use Markdown with these sections:\n\n"
        "1. A one-line '# ' title with the business name and what people searched for.\n"
        "2. **The bottom line** (2 to 4 sentences). Lead with the reach: how far from "
        "their shop they actually show up, using the reach figures, and say plainly "
        "that beyond that distance the people searching are finding a competitor "
        "instead. Make clear the area where they do not show up is not a few scattered "
        "spots, it is everything past that edge, the whole rest of the city and every "
        "customer in it. If the reach is short, say so directly. This is the headline "
        "and it should land as a real problem, not a neutral fact.\n"
        "3. **Where people find you, and where they don't.** Name the neighborhoods and "
        "directions where they show up near the top, and the ones where they do not "
        "show up at all. Note where the edge of their visibility is closest in (the "
        "weakest direction) versus farthest out.\n"
        "4. **Who shows up instead.** Name the specific competitors winning the areas "
        "they are missing.\n"
        "5. **Why.** Separate the part that is just distance (which they cannot change) "
        "from the specific things they can fix. Use the real gap numbers (reviews, "
        "photos, and so on) in plain terms.\n"
        "6. **What to do**, in order of what will help most, plain and specific.\n"
        "7. **The honest truth**: a short, straight paragraph on how far this can "
        "realistically go, per the honesty rule.\n\n"
        "Return only the Markdown."
    )
    return _call(prompt, max_tokens=4000)


def _strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.strip()


def write_content(findings, analysis_md):
    """Draft a service-area page and a GBP post per weak zone.

    Returns (data, usage, model) where data is {"pages": [...], "posts": [...]}.
    The model is asked for strict JSON so parsing is reliable across models; the
    LocalBusiness JSON-LD is built in Python, not here, because it is data.
    """
    prompt = (
        "Here is the findings file:\n\n"
        "```json\n" + json.dumps(findings, indent=2) + "\n```\n\n"
        "Here is the ranking analysis already written for this business:\n\n"
        + analysis_md + "\n\n"
        "Draft marketing content for each weak zone in the findings. For each weak "
        "zone produce:\n"
        "  - a service-area web page in Markdown, targeting that real neighborhood. "
        "Reference the actual place name, how people there search for this service, "
        "and the specific named competitor to displace. Name a real, closable gap "
        "from the findings as a reason to choose this business. Do not write generic "
        "'Best [service] in [city]' filler. Where a genuinely local detail (a "
        "landmark, a street) would help but is not in the findings, leave an HTML "
        "comment telling the operator to add it. Do not invent local details.\n"
        "  - one short Google Business Profile post (under 1500 characters) pointed at "
        "that same zone.\n\n"
        "Return ONLY a JSON object, no prose and no code fences, of the form:\n"
        '{\"pages\":[{\"place\":\"...\",\"slug\":\"kebab-case\",\"markdown\":\"...\"}],'
        '\"posts\":[{\"place\":\"...\",\"text\":\"...\"}]}\n'
        "Every rule in your instructions applies to every word: no em dashes, no "
        "'free', no 'snapshot', no overpromising on reach."
    )
    text, usage, model = _call(prompt, max_tokens=8000)
    try:
        data = json.loads(_strip_fences(text))
    except ValueError:
        data = {"pages": [], "posts": [], "_raw": text}
    data.setdefault("pages", [])
    data.setdefault("posts", [])
    return data, usage, model
