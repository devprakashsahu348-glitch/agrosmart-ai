# AgroSmart AI - Precision Farming & Soil Health Intelligence

An **offline-first** decision-support web app: farm records, soil health analysis, crop recommendation (trained model), yield estimation (trained model + real historical statistics), fertiliser guidance, farming advisory, analytics and PDF reports.
Flask + SQLite + scikit-learn + Chart.js (bundled) + ReportLab. Runs on `localhost`, no internet needed after installation, no paid APIs.

> It is a **decision-support prototype**, not certified agronomic advice. Every result page says so.

---------------------------------------------------------------------

## 1. Install (Windows)

1. Install **Python 3.10 or newer** from python.org (tick *Add Python to PATH*).
2. Unzip this folder anywhere.
3. Double-click **`setup.bat`** (needs internet **once** to download packages, then trains the two models, ~1 minute).
4. Double-click **`run.bat`**. Your browser opens at <http://127.0.0.1:5000>.

Linux/macOS: `./setup.sh` then `./run.sh`.  Manual: `python -m venv venv`, activate it, `pip install -r requirements.txt`, `python train_models.py`, `python app.py`.

### Installing with no internet at all (hackathon venue)
On any computer **with** internet (same Windows + Python version):
```
pip download -r requirements.txt -d wheels
```
Copy the `wheels` folder next to `setup.bat`. `setup.bat` detects it and installs fully offline.

### Check that it works offline
Install first, then switch off Wi-Fi / unplug the network and run `run.bat`. Everything (pages, charts, models, PDFs) still works because nothing is loaded from the internet: Chart.js is in `static/vendor/`, fonts are system fonts, icons are inline SVG.

---------------------------------------------------------------------

## 2. Demo guide for judges (about 5 minutes)

1. **Open the dashboard** - empty counters and a hint to load demo data.
2. Click **Load Demo Data** - adds 4 clearly labelled *DEMO* farms with sample soil values; the models then run on them. Your own records are never touched or overwritten (reloading asks for confirmation and only replaces DEMO-flagged rows).
3. **My Farms -> open "Demo Farm A - Rice Field"**. Show edit, search and the delete confirmation (don't delete!).
4. Click **Enter soil measurements** (or *Soil Health*): use *Fill example values*, or type your own. Try `pH 15` to show validation errors. Leave optional fields blank to show they are listed as *missing*, not assumed.
5. **Run soil analysis** - ratings, two charts, "what it means", reliability note. Open **Fertiliser guidance** from the report (general guidance, no dosages, warning shown).
6. **Crop Recommendations** - click an example chip (e.g. *Rice*) and run. Show top 3, score, soil/climate/water/season/limitations, the **compare table**, and the **"what influenced this"** explanation.
7. Click **Estimate yield** on a crop card (or *Yield Prediction*): choose farm, crop, state, season, area/unit. Show estimate, spread, total production (= t/ha x hectares), the **comparison with real historical records** and the **model information** (MAE, R2 vs a simple baseline).
8. **Analytics** - change the farm / "records shown" filters; charts update. Pick a crop + state to see the real historical series.
9. **Reports** - **Download PDF** for the soil, crop and yield records.
10. **About Project** shows the problem, solution, limitations and full model evaluation.

### What to say about the models (honest answers to likely questions)
* **Crop model**: Random Forest, 80/20 stratified split, ~99.6% test accuracy. *"That measures the dataset, which is very cleanly separated; it is not field accuracy."*
* **Yield model**: Random Forest on state-level government statistics, tested on **years it never saw** (2016-2019). It beats a simple "historical median" baseline (see the table in the app) but errors are still large for many crops. Rainfall, soil and irrigation are **not** in the data, so they are not modelled; the app says so.
* The spread shown with a yield estimate is the disagreement between trees, **not** a confidence interval.
* Soil ratings come from commonly used Indian soil-test classes (Soil Health Card style), not from machine learning.

---------------------------------------------------------------------

## 3. Project structure
```
app.py                  Flask routes
config.py               settings (secret key generated on first run, never hard-coded)
train_models.py         trains + saves both models to models/saved/
database/               schema.sql (tables) + db.py (parameterised-query helpers)
models/                 crop_recommender.py, yield_predictor.py, saved/ (joblib files + metrics json)
services/               soil_analysis.py, recommendation_service.py, report_service.py, validation.py
data/                   crop_information.json, advisory_data.json, demo_farms.json, datasets/
templates/ static/      HTML, CSS, JS, vendor/chart.umd.js, landing/ (project overview page)
scripts/                prepare_yield_data.py (rebuild the yield dataset)
tests/                  automated tests (37)
instance/               agrosmart.db is created here on first run
```

## 4. Run the tests
```
python -m unittest discover -s tests -t .
```
Tests use a temporary database, so your data is safe.

## 5. Security notes
Server-side validation of every field; parameterised SQL only; CSRF token on every POST; auto-escaped HTML; strict Content-Security-Policy (scripts/styles only from this server); delete actions use POST + confirmation; no uploads; no secrets in code; binds to `127.0.0.1` only. To share on a LAN deliberately: set `AGROSMART_HOST=0.0.0.0` (the app has **no login**, so only do this on a trusted network).

## 6. Troubleshooting
| Problem | Fix |
|---|---|
| `python` not recognised | Reinstall Python and tick *Add Python to PATH*, or use `py -m venv venv` |
| `pip install` fails / no internet | Use the offline `wheels` method above |
| Port 5000 already in use | `set AGROSMART_PORT=5001` then `run.bat` (or edit `run.bat`) |
| "Please run setup.bat first" | `venv` folder is missing: run `setup.bat` |
| Models re-train on start-up | The saved model was made with another scikit-learn version. It trains automatically (about 1 minute) and saves again. |
| Page shows "Form session expired" | The page was open a long time or cookies are blocked. Refresh and resubmit. |
| Want to reset everything | *Settings -> Delete all data*, or stop the app and delete `instance/agrosmart.db` |
| PDF shows `?` in a name | Built-in PDF fonts only support Latin characters; non-Latin text is replaced |

## 7. Known limitations
* Predictions depend on dataset quality and may not generalise to every region or season.
* Crop model: no soil-type input in its dataset; N/P/K are on the dataset's scale (not lab kg/ha), so Soil Health and Crop Recommendation use separate N/P/K units on purpose.
* Yield model: state-level averages only; no weather, soil or irrigation inputs; the uncertainty range is tree disagreement, not a confidence interval; 35 crops with tonne-based records only.
* No authentication (single local user); no multi-language UI; PDFs support Latin text only.
* Soil classes are general; crop-specific, state-specific limits can differ. No fertiliser doses are given by design.

## 8. Future improvements
Weather/rainfall inputs for yield; district-level models; Hindi/Bengali/other languages; user login; CSV import/export; photo-based leaf disease detection (needs a validated dataset); soil-type aware recommendation with a suitable dataset; field-trial validation with agricultural experts.
