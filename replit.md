# Meme Stock Predictor

## Overview
Sentiment analysis web app built from the imported "Trend Terminal" project bundle. Users enter a stock ticker (1–5 letters) and get the crowd sentiment (Positive / Negative / Neutral, with a score) computed from 110 pre-labeled r/wallstreetbets posts, plus a live market snapshot via yfinance. A secondary section lets users classify their own post text with the bundled model (flair rules + OpenAI LLM judge).

## Architecture
- `app.py` — Flask backend; serves the static frontend and JSON API:
  - `GET /api/overview` — dataset stats + example tickers
  - `GET /api/predict/<ticker>` — sentiment verdict, score, breakdown, sample posts, live/snapshot price
  - `POST /api/classify` — classify custom text (needs `OPENAI_API_KEY` unless flair maps by rule)
- `static/` — vanilla HTML/CSS/JS frontend, Scandinavian-minimal design (Inter + Fraunces, pine-green accent)
- Imported model bundle (do not restructure):
  - `meme_stock_classifier.py` — classification logic (OpenAI gpt-5.4-mini + flair rules)
  - `stock_data.py` — yfinance price helpers
  - `wsb_labeled.csv` / `ticker_prices.csv` — labeled posts + price snapshot, loaded via `model_setup.paths`
  - `model_setup.py` — file path resolver (HF Hub fallback, unused here)

## Running
- Dev workflow "Start application": `python app.py` on port 5000 (binds 0.0.0.0, honors `PORT`).
- Deployment: autoscale, `gunicorn --bind=0.0.0.0:5000 --reuse-port app:app`.
- Live price fetches fall back to the bundled `ticker_prices.csv` snapshot if yfinance fails.

## Secrets
- `OPENAI_API_KEY` (optional for main flow) — required only for the "classify your own post" feature. Must also be set in Deployment secrets for production.
