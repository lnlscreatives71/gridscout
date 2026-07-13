# gridscout

Grid-based Google Maps rank tracking. Shows you exactly where a business ranks
across every neighborhood of a city, block by block, and where it is invisible.

Local Falcon / Lensly, but yours, and about ten cents a scan.

The map is the product. The AI layer on top of it turns a scan into a written
ranking analysis and a folder of ready-to-edit local content, with one rule
above all: it never promises more than the data supports.

---

## What it does

Five commands. Each is independent and each can run off a saved scan, so you
never rescan just to regenerate a report.

- `scan`     runs the grid, saves it, prints an ASCII map, writes an interactive
             HTML heatmap and a JSON file.
- `analyze`  writes the ranking analysis. Where you are strong, where you are
             invisible, who is winning there, why, and what to do, ranked by
             leverage.
- `content`  drafts a service-area page and a Google Business Profile post for
             each weak neighborhood, plus `LocalBusiness` schema. Publishes
             nothing.
- `report`   assembles a branded PDF heatmap report.
- `history`  shows visibility over time for the same business and keyword.

---

## How the AI layer stays honest

Python does the math. The model does the language. Never the other way around.

Every `analyze` run first computes everything deterministically and writes it to
`output/<name>-<id>-findings.json`: the weak zones in geographic terms, the
dominant competitor in each, the rank deltas, the review, rating, photo,
category, and attribute gaps, claimed status, and description coverage. Every
number in that file is calculated.

The model then receives that file and writes prose from it. It is never asked to
compute a rank, invent a competitor, or estimate a gap. If a number appears in a
report, it came from the findings file, which means the reports do not
hallucinate and you can always rewrite the copy by hand off the same file.

Proximity dominates the local pack, and no page beats physical distance. The copy
says exactly that. What content and profile work do is push relevance and
prominence, which stretches your visible radius at the margins. That is the
promise. Nothing bigger.

---

## Setup

### 1. Check Python

```
python3 --version
```

3.12 or higher. Your Mac already has this.

### 2. Install the one dependency for the AI features

The scan, heatmap, and history commands run on the standard library alone. The
`analyze`, `content`, and `report` commands call the Anthropic API, which needs
the `anthropic` package. Install it into a local virtual environment:

```
python3 -m venv .venv
.venv/bin/python -m pip install anthropic
```

`report` also needs WeasyPrint for the PDF. If you already use it (`brew install
weasyprint`), gridscout finds it automatically. If not, `report` still writes the
report HTML so you can print it to PDF from a browser.

### 3. Try it with the mock first

No account, no key, no cost.

```
python3 -m gridscout.cli scan \
  --business "Summit Air & Heating" \
  --keyword "hvac repair" \
  --lat 39.9612 --lng -82.9988 \
  --provider mock
```

Open the `.html` file in `output/`. That is the heatmap. The competitor dropdown
in the sidebar is the feature to show a prospect: pick any business that appeared
in the scan and every pin re-renders with that business's rank.

The mock builds a realistic market around whatever center you give it and drops
the business you typed in at that center, so it produces a believable map for any
city and any business name.

---

## Going live

### 1. DataForSEO (the map data)

Sign up at dataforseo.com. They give you a dollar of trial credit, no card, which
is about ten scans.

Go to `app.dataforseo.com/api-access`. Copy the **API login** and **API
password**. These are NOT your website login. They are a separate pair.

### 2. Anthropic (the writing)

Get a key at `console.anthropic.com/settings/keys`. It starts with `sk-ant-`.

### 3. Put both in a .env file

```
cp .env.example .env
```

Open `.env`, paste your values, save. `.env` is gitignored and will never be
pushed.

```
source .env
```

### 4. Run

```
# a live scan
python3 -m gridscout.cli scan \
  --business "Real Business Name" \
  --keyword "what people search" \
  --lat 39.9612 --lng -82.9988 \
  --provider dataforseo

# the analysis and content run through the venv (they use the anthropic package)
.venv/bin/python -m gridscout.cli analyze
.venv/bin/python -m gridscout.cli content
.venv/bin/python -m gridscout.cli report
```

Each of the last three defaults to the latest scan. Pass a scan id to target an
older one: `analyze 3`.

---

## Cost control

Model output is cached alongside each scan, so re-running `report` does not
regenerate the analysis. Pass `--refresh` to force it.

Every run prints its real spend, itemized: DataForSEO cost read straight from the
API response, and Anthropic cost from the actual token usage. A full scan,
analysis, and content pass lands well under a dollar per prospect.

---

## Getting the lat/lng

Open Google Maps, right click the business, and the first item in the menu is the
coordinates. Click to copy. First number is lat, second is lng.

---

## Options

```
--size 7        points per side. 7 = 49 pins. 9 = 81 pins.
--radius 3      miles from center to edge. Dense city: 2. Spread out: 5.
--depth 20      how deep to look before calling the business "not found"
--provider      mock | dataforseo
--refresh       analyze/content/report: regenerate instead of using the cache
--no-geo        analyze/content/report: skip the OpenStreetMap name lookups
```

Scan cost is roughly `size x size x $0.002`. A 7x7 is about ten cents.

---

## What's in the box

```
gridscout/
  grid.py            builds the lat/lng lattice
  scanner.py         runs the scan, matches the business, scores it
  heatmap.py         the interactive HTML map with the competitor overlay
  store.py           SQLite: ranking history and the model-output cache
  geo.py             compass zones and real neighborhood names (keyless OSM)
  analysis.py        the deterministic reasoning core
  findings.py        writes the findings file the model reads from
  llm.py             the Anthropic layer and its honesty rules
  content.py         assembles the content folder
  report.py          the branded PDF
  cli.py             the commands
  providers/
    mock.py          realistic fake data, no key needed
    dataforseo.py    the live one
output/              your scans, heatmaps, findings, reports, and drafts land here
```
