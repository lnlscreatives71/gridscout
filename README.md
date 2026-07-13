# gridscout

Grid-based Google Maps rank tracking. Shows you exactly where a business ranks
across every neighborhood of a city, block by block, and where it's invisible.

Local Falcon / Lensly, but yours, and about ten cents a scan.

---

## Setup (one time, about 5 minutes)

### 1. Put this folder somewhere

```
cd ~/Projects        # or wherever you keep things
# move the gridscout folder here
cd gridscout
```

### 2. Check Python

```
python3 --version
```

Anything 3.10 or higher is fine. Your Mac already has this.

There is nothing to install. No pip, no venv, no dependencies. The whole tool
runs on Python's standard library.

### 3. Try it with fake data first

```
python3 -m gridscout.cli scan \
  --business "Summit Air & Heating" \
  --keyword "hvac repair" \
  --lat 39.9612 --lng -82.9988 \
  --provider mock
```

You'll get a grid printed in your terminal and two files in `output/`.
Open the `.html` one in your browser. That's the heatmap.

This costs nothing and needs no account. It proves the tool works before you
spend a cent.

---

## Going live (when you're ready)

### 1. Make a DataForSEO account

Go to dataforseo.com, sign up. They give you $1 of free credit, no card needed.
That's about 10 full scans.

### 2. Get your API credentials

Go to `app.dataforseo.com/api-access`.

You'll see an **API login** and an **API password**. These are NOT the same as
the email and password you log into the website with. It's a separate pair they
generate for you.

### 3. Put them in a .env file

Copy `.env.example` to `.env`:

```
cp .env.example .env
```

Open `.env` and paste your two values in. Save it.

`.env` is already in `.gitignore`, so it will never get pushed to GitHub.

### 4. Run a real scan

```
source .env
python3 -m gridscout.cli scan \
  --business "Real Business Name" \
  --keyword "what people search" \
  --lat 39.9612 --lng -82.9988 \
  --provider dataforseo
```

That's it.

---

## Getting the lat/lng

Open Google Maps, right click on the business, and the first item in the menu is
the coordinates. Click it to copy. First number is lat, second is lng.

---

## Options

```
--size 7        points per side. 7 = 49 pins. 9 = 81 pins.
--radius 3      miles from center to edge. Dense city: 2. Spread out: 5.
--depth 20      how deep to look for the business before calling it "not found"
--provider      mock | dataforseo
```

Cost is roughly `size x size x $0.002`. A 7x7 is about 10 cents.

---

## Ranking history

Every scan is saved automatically. Run the same business and keyword again in a
month and:

```
python3 -m gridscout.cli history \
  --business "Real Business Name" \
  --keyword "what people search"
```

You'll see visibility over time. That's the client retention feature.

---

## What's in the box

```
gridscout/
  grid.py            builds the lat/lng lattice
  scanner.py         runs the scan, matches the business, scores it
  heatmap.py         renders the interactive HTML map
  store.py           SQLite, gives you ranking history for free
  cli.py             the commands
  providers/
    mock.py          fake data, no key needed
    dataforseo.py    the live one
output/              your scans land here
```

## Not built yet

AI Ranking Coach, neighborhood page generator, GBP post generator, PDF report.
Next up.
