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
SYSTEM = """You are the writer for a local-SEO grid rank tracking tool. You are given a
findings file: a JSON object of numbers a separate program already calculated from a
real scan of Google Maps rankings. Your only job is to turn those numbers into clear,
useful writing for a US small-business owner.

Hard rules, no exceptions:

1. Every number you state must come from the findings file. Never compute, estimate,
   or invent a rank, a competitor, a review count, a distance, or a gap. If the file
   does not contain a figure, do not state one.
2. Never use em dashes. Use periods, commas, or the word "and".
3. Never use the words "free" or "snapshot".
4. Never claim a business can rank everywhere, rank first across a whole city, or that
   content "lights up the map". Proximity dominates the local pack and no page beats
   physical distance. What content and profile work do is push relevance and
   prominence, which stretches the visible radius at the margins. That is the promise.
   Nothing bigger. Honor the honesty_constraint field in the findings.
5. Describe location geographically, using the real place names and directions in the
   findings, never grid coordinates, rows, or columns.
6. Write direct, plain, outcome-focused prose. No corporate filler, no "certainly", no
   "great question", no hype. If the data does not support a claim, do not make it."""


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
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = {"input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens}
    return text, usage, model


def write_analysis(findings):
    """The AI Ranking Coach writeup. Returns (markdown, usage, model)."""
    prompt = (
        "Here is the findings file for a scan:\n\n"
        "```json\n" + json.dumps(findings, indent=2) + "\n```\n\n"
        "Write the ranking coach analysis as Markdown. Cover, in this order:\n"
        "1. Where the business is strong and where it is invisible, in the real "
        "directional and neighborhood terms from the findings.\n"
        "2. Who is winning the ground it is losing. Name the dominant competitor in "
        "each weak zone.\n"
        "3. The specific, named reason those competitors win there. Separate the part "
        "that is pure distance from the part that is a closable gap (reviews, rating, "
        "photos, categories, attributes, description), using the gap figures.\n"
        "4. What to do about it, ranked by leverage, ending with an honest note on the "
        "ceiling that proximity sets.\n\n"
        "Use a plain '# ' heading with the business name and keyword. Return only the "
        "Markdown."
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
