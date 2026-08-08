const $ = (id) => document.getElementById(id);

const fmtCap = (v) => {
  if (!v) return "—";
  if (v >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (v >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(0) + "M";
  return String(v);
};
const fmtPrice = (v) => (v || v === 0) ? "$" + Number(v).toFixed(2) : "—";

let llmAvailable = false;

async function loadOverview() {
  try {
    const r = await fetch("/api/overview");
    const d = await r.json();
    llmAvailable = d.llm_available;
    $("keyNote").hidden = llmAvailable;
    const s = d.summary;
    $("datasetPill").textContent =
      `${s.total} posts · ${s.Positive.pct}% pos / ${s.Negative.pct}% neg / ${s.Neutral.pct}% neu`;
    if (d.examples.length) {
      $("examples").hidden = false;
      const chips = $("exampleChips");
      chips.textContent = "";
      d.examples.forEach((raw) => {
        const t = String(raw).toUpperCase().replace(/[^A-Z]/g, "").slice(0, 5);
        if (!t) return;
        const b = document.createElement("button");
        b.type = "button"; b.className = "chip"; b.textContent = t;
        b.addEventListener("click", () => { $("tickerInput").value = t; predict(t); });
        chips.appendChild(b);
      });
    }
  } catch { $("datasetPill").textContent = "dataset unavailable"; }
}

function setStatus(text, isError = false, loading = false) {
  const el = $("status");
  el.hidden = !text;
  el.className = "status" + (isError ? " error" : "");
  el.textContent = "";
  if (!text) return;
  if (loading) {
    const sp = document.createElement("span");
    sp.className = "spinner";
    el.appendChild(sp);
  }
  el.appendChild(document.createTextNode(text));
}

async function predict(ticker) {
  ticker = String(ticker).toUpperCase().replace(/[^A-Z]/g, "").slice(0, 5);
  if (!ticker) { setStatus("Enter a ticker: 1–5 letters, e.g. NVDA.", true); return; }
  setStatus(`Reading the room on ${ticker}…`, false, true);
  $("result").hidden = true;
  try {
    const r = await fetch(`/api/predict/${encodeURIComponent(ticker)}`);
    const d = await r.json();
    if (!r.ok) { setStatus(d.error || "Something went wrong.", true); return; }
    setStatus("");
    render(d);
  } catch {
    setStatus("Could not reach the server.", true);
  }
}

function render(d) {
  $("result").hidden = false;

  // verdict
  const v = d.verdict;
  const vt = $("verdictText");
  if (v === null) {
    vt.textContent = "No chatter";
    vt.className = "verdict neutral";
    $("scoreValue").textContent = "";
    $("scoreFill").style.width = "0";
    $("mentionsText").textContent = `No posts mention ${d.ticker} in the labeled dataset.`;
    $("bars").innerHTML = "";
  } else {
    vt.textContent = v;
    vt.className = "verdict " + v.toLowerCase();
    const score = d.score; // -1..1
    $("scoreValue").textContent = (score > 0 ? "+" : "") + score.toFixed(2);
    const fill = $("scoreFill");
    const pct = Math.abs(score) * 50;
    fill.style.width = pct + "%";
    fill.style.left = score >= 0 ? "50%" : (50 - pct) + "%";
    fill.style.background = score > 0.15 ? "var(--pos)" : score < -0.15 ? "var(--neg)" : "var(--neu)";
    $("mentionsText").textContent = `${d.mentions} post${d.mentions === 1 ? "" : "s"} mention ${d.ticker}`;

    const b = d.breakdown, total = d.mentions || 1;
    $("bars").innerHTML = ["positive", "negative", "neutral"].map((k) => `
      <div class="bar-row">
        <span>${k[0].toUpperCase() + k.slice(1)}</span>
        <div class="bar-track"><div class="bar-fill ${k}" style="width:${(b[k] / total) * 100}%"></div></div>
        <span class="bar-count">${b[k]}</span>
      </div>`).join("");
  }

  // stock
  const s = d.stock;
  $("stockName").textContent = s.name ? `${s.name} · ${d.ticker}` : d.ticker;
  $("stockPrice").textContent = fmtPrice(s.current_price);
  const delta = $("stockDelta");
  if (s.price_change_pct || s.price_change_pct === 0) {
    const up = s.price_change_pct >= 0;
    delta.textContent = (up ? "▲ " : "▼ ") + Math.abs(s.price_change_pct).toFixed(2) + "%";
    delta.className = "delta " + (up ? "up" : "down");
  } else { delta.textContent = ""; }

  const facts = $("stockFacts");
  facts.textContent = "";
  [["Sector", s.sector || "—"],
   ["Market cap", fmtCap(s.market_cap)],
   ["52-wk high", fmtPrice(s.week_52_high)],
   ["52-wk low", fmtPrice(s.week_52_low)],
  ].forEach(([k, val]) => {
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = String(val);
    div.append(dt, dd);
    facts.appendChild(div);
  });

  $("sourceNote").textContent =
    s.source === "live" ? "Live data via Yahoo Finance" :
    s.source === "snapshot" ? "From bundled price snapshot (live fetch unavailable)" :
    "Price data unavailable for this ticker";

  // posts
  const pc = $("postsCard");
  if (d.posts.length) {
    pc.hidden = false;
    const list = $("postsList");
    list.textContent = "";
    const SENTS = ["positive", "negative", "neutral"];
    d.posts.forEach((p) => {
      const li = document.createElement("li");
      const sent = SENTS.includes(String(p.sentiment).toLowerCase()) ? String(p.sentiment).toLowerCase() : "neutral";
      const tag = document.createElement("span");
      tag.className = "tag " + sent;
      tag.textContent = p.sentiment || "—";
      const title = document.createElement("span");
      title.className = "post-title";
      let url = null;
      try { const u = new URL(p.url); if (u.protocol === "https:" || u.protocol === "http:") url = u.href; } catch {}
      if (url) {
        const a = document.createElement("a");
        a.href = url; a.target = "_blank"; a.rel = "noopener";
        a.textContent = p.title;
        title.appendChild(a);
      } else { title.textContent = p.title; }
      const score = document.createElement("span");
      score.className = "post-score";
      score.textContent = "▲ " + Number(p.score || 0).toLocaleString();
      li.append(tag, title, score);
      list.appendChild(li);
    });
  } else { pc.hidden = true; }

  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("tickerInput").value.trim().toUpperCase();
  if (t) predict(t);
});

$("classifyBtn").addEventListener("click", async () => {
  const text = $("classifyText").value.trim();
  const out = $("classifyResult");
  if (!text) { out.textContent = "Enter some text first."; out.className = "classify-result error"; return; }
  out.textContent = "Thinking…";
  out.className = "classify-result";
  try {
    const r = await fetch("/api/classify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const d = await r.json();
    if (!r.ok) { out.textContent = d.error; out.className = "classify-result error"; return; }
    out.textContent = d.sentiment + (d.ticker ? ` · $${d.ticker}` : "");
    out.className = "classify-result " + d.sentiment.toLowerCase();
  } catch {
    out.textContent = "Request failed.";
    out.className = "classify-result error";
  }
});

loadOverview();
