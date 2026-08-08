import os
import re
import threading

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

import model_setup
import meme_stock_classifier as msc
import stock_data

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # 16 KB request bodies are plenty

# ---------------------------------------------------------------- data load
_df_lock = threading.Lock()
_df = None
_snapshot = None


def get_df():
    global _df
    with _df_lock:
        if _df is None:
            _df = pd.read_csv(model_setup.paths["wsb_labeled.csv"])
        return _df


def get_snapshot():
    global _snapshot
    with _snapshot_lock:
        if _snapshot is None:
            _snapshot = pd.read_csv(model_setup.paths["ticker_prices.csv"])
        return _snapshot


_snapshot_lock = threading.Lock()

# Words that look like tickers but aren't
_TICKER_STOP = {
    "YOLO", "DD", "CEO", "CFO", "USA", "ETF", "IPO", "THE", "AND", "FOR",
    "NOT", "ALL", "GAIN", "LOSS", "WSB", "ATH", "EPS", "SEC", "API", "OTM",
    "ITM", "FD", "FDS", "PDT", "AI", "US", "UK", "EU", "IMO", "LMAO", "WTF",
    "TLDR", "EDIT", "BUY", "SELL", "PUT", "CALL", "HOLD", "HODL", "NEW",
    "BIG", "RED", "LOL", "OK", "GG", "ONE", "DOE", "IRS", "GDP", "FED",
}


def _post_text(row):
    return f"{row.get('title', '')} {row.get('body', '')}"


def posts_mentioning(df, ticker):
    """Posts whose title/body mention the ticker.

    Short symbols (1-2 letters) only match as cashtags ($A, $PI) to avoid
    matching ordinary words; longer symbols also match as bare words.
    """
    if len(ticker) <= 2:
        pattern = re.compile(rf"\${ticker}\b")
    else:
        pattern = re.compile(rf"(?:\${ticker}\b)|(?:\b{ticker}\b)", re.IGNORECASE)
    mask = df.apply(lambda r: bool(pattern.search(_post_text(r))), axis=1)
    return df[mask]


# ------------------------------------------------------------- price cache
_PRICE_TTL = 300  # seconds
_price_cache = {}
_price_lock = threading.Lock()


def cached_stock_info(ticker):
    import time
    now = time.monotonic()
    with _price_lock:
        hit = _price_cache.get(ticker)
        if hit and now - hit[0] < _PRICE_TTL:
            return hit[1]
    info = stock_data.get_stock_info(ticker)
    if not info.get("error") and info.get("current_price"):
        with _price_lock:
            _price_cache[ticker] = (now, info)
    return info


def dataset_tickers(df, n=8):
    """Most-mentioned real-looking tickers across the dataset."""
    from collections import Counter
    counts = Counter()
    for _, row in df.iterrows():
        text = _post_text(row)
        for m in re.findall(r"\$([A-Za-z]{1,5})\b", text):
            counts[m.upper()] += 2  # cashtags are high confidence
        for m in re.findall(r"\b([A-Z]{2,5})\b", text):
            if m not in _TICKER_STOP:
                counts[m] += 1
    return [t for t, c in counts.most_common(n * 2) if c >= 2][:n]


# ------------------------------------------------------- classify rate limit
_RATE_LIMIT = 10          # requests
_RATE_WINDOW = 60         # per seconds, per client IP
_rate_hits = {}
_rate_lock = threading.Lock()


def _classify_allowed(ip):
    import time
    now = time.monotonic()
    with _rate_lock:
        hits = [t for t in _rate_hits.get(ip, []) if now - t < _RATE_WINDOW]
        if len(hits) >= _RATE_LIMIT:
            _rate_hits[ip] = hits
            return False
        hits.append(now)
        _rate_hits[ip] = hits
        if len(_rate_hits) > 10000:  # bound memory
            _rate_hits.clear()
        return True


# ---------------------------------------------------------------- routes
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/overview")
def overview():
    df = get_df()
    summary = msc.get_sentiment_summary(df)
    return jsonify({
        "summary": summary,
        "examples": dataset_tickers(df),
        "llm_available": bool(os.environ.get("OPENAI_API_KEY")),
    })


@app.route("/api/predict/<ticker>")
def predict(ticker):
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}", ticker):
        return jsonify({"error": "Enter a valid ticker: 1–5 letters, e.g. NVDA."}), 400

    df = get_df()
    matches = posts_mentioning(df, ticker)

    counts = matches["sentiment"].value_counts() if not matches.empty else {}
    pos = int(counts.get("Positive", 0))
    neg = int(counts.get("Negative", 0))
    neu = int(counts.get("Neutral", 0))
    total = pos + neg + neu

    if total == 0:
        verdict, score = None, None
    else:
        score = round((pos - neg) / total, 3)  # -1 .. +1
        verdict = "Positive" if score > 0.15 else "Negative" if score < -0.15 else "Neutral"

    # live price (fall back to bundled snapshot)
    info = stock_data.get_stock_info(ticker)
    price_source = "live"
    if info.get("error") or not info.get("current_price"):
        snap = get_snapshot()
        row = snap[snap["ticker"].str.upper() == ticker]
        if not row.empty:
            r = row.iloc[0].to_dict()
            info = {
                "ticker": ticker, "name": r.get("name", ticker),
                "sector": r.get("sector", "Unknown"),
                "current_price": r.get("current_price"),
                "price_change_pct": r.get("price_change_pct"),
                "market_cap": r.get("market_cap"),
                "week_52_high": r.get("week_52_high"),
                "week_52_low": r.get("week_52_low"),
                "error": None,
            }
            price_source = "snapshot"
        else:
            price_source = "unavailable"

    sample_posts = []
    if not matches.empty:
        top = matches.sort_values("score", ascending=False).head(5)
        for _, row in top.iterrows():
            sample_posts.append({
                "title": str(row.get("title", ""))[:180],
                "sentiment": row.get("sentiment"),
                "score": int(row.get("score", 0)),
                "flair": None if pd.isna(row.get("flair")) else str(row.get("flair")),
                "url": None if pd.isna(row.get("url")) else str(row.get("url")),
            })

    return jsonify({
        "ticker": ticker,
        "verdict": verdict,
        "score": score,
        "mentions": total,
        "breakdown": {"positive": pos, "negative": neg, "neutral": neu},
        "posts": sample_posts,
        "stock": {
            "name": info.get("name"),
            "sector": info.get("sector"),
            "current_price": info.get("current_price"),
            "price_change_pct": info.get("price_change_pct"),
            "market_cap": info.get("market_cap"),
            "week_52_high": info.get("week_52_high"),
            "week_52_low": info.get("week_52_low"),
            "source": price_source,
        },
    })


@app.route("/api/classify", methods=["POST"])
def classify():
    """Classify a custom post with the bundled model (flair rules + OpenAI LLM judge)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send a JSON object with a 'text' field."}), 400
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Post text is required."}), 400
    text = text.strip()
    if len(text) > 600:
        return jsonify({"error": "Post text is too long (max 600 characters)."}), 400
    flair = data.get("flair")
    if not isinstance(flair, str) or flair not in msc.FLAIR_LABEL_MAP:
        flair = None
    if not _classify_allowed(request.remote_addr or "unknown"):
        return jsonify({"error": "Too many requests — try again in a minute."}), 429
    needs_llm = not (flair and flair in msc.FLAIR_LABEL_MAP)
    if needs_llm and not os.environ.get("OPENAI_API_KEY"):
        return jsonify({"error": "OPENAI_API_KEY is not set — add it in Secrets to classify custom posts."}), 503
    try:
        result = msc.classify_post(text, flair=flair)
        return jsonify(result)
    except Exception:
        app.logger.exception("classification failed")
        return jsonify({"error": "Classification failed — please try again."}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
