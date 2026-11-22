# CarbonLensAI

A Flask-based carbon-footprint estimation MVP with a responsive dashboard, calculation history, electricity-bill OCR, optional Gemini vision, AI/rule-based recommendations, and route comparisons.

## Run locally (Windows PowerShell)

```powershell
cd Carbon-Lens-Ai-main
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open http://127.0.0.1:5000. The app creates `carbonlens.db` automatically. Calculations and the saved commute routine persist in that local SQLite database.

## Optional Gemini features

1. Get a Gemini API key from Google AI Studio.
2. Put it in `.env` as `GEMINI_API_KEY=your_key`.
3. The app loads `.env` automatically through `python-dotenv`, or you can set the environment variable in PowerShell:

```powershell
$env:GEMINI_API_KEY="your_key"
python app.py
```

Without the key, recommendations still work using built-in rules. Food image classification is disabled and the UI explains why; manual food-category selection remains available. Do not commit `.env` or expose the API key in frontend JavaScript.

## What is implemented

- Validated carbon calculations via `/api/calculate` using the project's supplied emission-factor assumptions.
- SQLite-backed latest-30 calculation history and a saved daily commute baseline.
- Electricity bill OCR in the browser using Tesseract.js. OCR is a suggestion and should be checked against the bill before calculating.
- Optional Gemini image classification via a server-side API call. It classifies a visible food category; it does **not** measure serving size or calculate an exact meal footprint.
- Tailored recommendations from Gemini when configured, otherwise deterministic rule-based suggestions.
- Place lookup with OpenStreetMap Nominatim and driving-route distance with OSRM. Public services are best-effort and subject to their usage policies and availability.
- Responsive dashboard layout for desktop and mobile.

## Important limitations before public launch

This is a functional local MVP, not a production multi-user SaaS. It has no user accounts, authorization, per-user data separation, rate limiting, CSRF protection, backups, or monitoring. SQLite is suitable for a small local/demo deployment, not a high-traffic multi-instance service. The emission factors are simplified illustrative values from the starter project and need authoritative, region-specific sources, units, boundaries, and citations before making scientific or public claims. The route comparison applies simple mode factors to one road-route distance; it is not a real multimodal route engine. OCR can misread numbers. Gemini vision may misclassify food. Validate all outputs.

## Deploy

For a single-instance demo host, use a persistent disk for `carbonlens.db`, set `GEMINI_API_KEY` as a secret if needed, and run:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

Use HTTPS. Do not use Flask's development server or `debug=True` in production. For a public product, add authentication, database migrations, rate limits, upload scanning, privacy/retention controls, observability, and independently sourced emission-factor data first.
