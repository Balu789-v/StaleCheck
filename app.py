"""StaleCheck - detects outdated claims in LLM-generated answers.

Pipeline:
  1. Extract time-sensitive claims   (LLM via Bifrost)
  2. Live-verify each claim          (Tavily web search)
  3. Judge + freshness score 0-100   (LLM via Bifrost, using ONLY Tavily sources)
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
from openai import OpenAI
from tavily import TavilyClient

load_dotenv()

# Every LLM call goes through the Bifrost gateway (OpenAI-compatible API).
BIFROST_URL = os.getenv("BIFROST_BASE_URL", "http://127.0.0.1:8080/v1")
MODEL = os.getenv("LLM_MODEL", "groq/openai/gpt-oss-120b")
llm = OpenAI(base_url=BIFROST_URL, api_key=os.getenv("BIFROST_API_KEY", "dummy"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

app = Flask(__name__)


def ask_llm(prompt: str):
    """Send a prompt through Bifrost and parse the JSON the model returns.
    Retries when the provider rate-limits us (HTTP 429)."""
    for attempt in range(5):
        try:
            resp = llm.chat.completions.create(
                model=MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": "Reply with valid JSON only. No markdown."},
                    {"role": "user", "content": prompt},
                ],
            )
            break
        except Exception as e:
            if "429" in str(e) and attempt < 4:
                time.sleep(12 * (attempt + 1))
                continue
            raise
    text = resp.choices[0].message.content.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return json.loads(text)


def extract_claims(answer: str):
    prompt = f"""Extract factual claims from the text below that could become
outdated (prices, software/API versions, laws, leadership, release dates,
statistics, rankings). Ignore timeless facts. Split compound sentences so each claim states ONE fact. Max 8 claims.

Return a JSON list:
[{{"claim": "...", "category": "pricing|api|law|leadership|other",
   "search_query": "short web search query to check it"}}]

Text: {answer}"""
    return ask_llm(prompt)


def verify_claim(item: dict):
    """Live check with Tavily, then score with the LLM."""
    sources = []
    for attempt in range(3):  # retry: Tavily can briefly rate-limit
        try:
            search = tavily.search(query=item["search_query"], max_results=3)
            sources = [
                {"title": r["title"], "url": r["url"], "content": r["content"][:300]}
                for r in search.get("results", [])
            ]
            item.pop("error", None)
            break
        except Exception as e:
            item["error"] = f"Search failed: {e}"
            print("TAVILY ERROR:", e)
            time.sleep(1.5 * (attempt + 1))

    if not sources:
        return {**item, "status": "unverifiable", "freshness_score": 0,
                "explanation": item.get("error", "No search results found."),
                "correction": "", "source_url": ""}

    prompt = f"""Today's date: {__import__('datetime').date.today()}.
Claim: {item['claim']}

Fresh web sources:
{json.dumps(sources, indent=1)}

Judge the claim using ONLY these sources. If they don't settle it, use "unverifiable".
Return JSON:
{{"status": "current|outdated|unverifiable",
  "freshness_score": 0-100 (100 = fully up to date),
  "explanation": "one sentence",
  "correction": "up-to-date fact, or empty string",
  "source_url": "best supporting url from the sources, or empty string"}}"""
    try:
        verdict = ask_llm(prompt)
    except Exception as e:
        verdict = {"status": "unverifiable", "freshness_score": 0,
                   "explanation": f"Judging failed: {e}", "correction": "", "source_url": ""}
    if verdict.get("status") == "outdated":
        verdict["freshness_score"] = min(int(verdict.get("freshness_score") or 0), 20)
    elif verdict.get("status") == "current":
        verdict["freshness_score"] = max(int(verdict.get("freshness_score") or 0), 80)
    elif verdict.get("status") == "unverifiable":
        verdict["freshness_score"] = min(int(verdict.get("freshness_score") or 0), 50)
    return {**item, **verdict}


@app.post("/api/check")
def check():
    answer = (request.json or {}).get("answer", "").strip()
    if not answer:
        return jsonify(error="Paste an answer first"), 400
    try:
        claims = extract_claims(answer)
        with ThreadPoolExecutor(max_workers=1) as pool:
            results = list(pool.map(verify_claim, claims))
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(results=results)


PAGE = """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StaleCheck</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:820px;margin:24px auto;padding:0 16px;background:#0f172a;color:#e2e8f0}
 h1{margin-bottom:4px} p.sub{color:#94a3b8;margin-top:0}
 textarea{width:100%;height:160px;padding:10px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;box-sizing:border-box}
 button{margin-top:10px;padding:10px 18px;border:0;border-radius:8px;background:#06b6d4;color:#00222b;font-weight:700;cursor:pointer}
 .card{margin-top:14px;padding:14px;border-radius:10px;background:#1e293b;border-left:6px solid #64748b}
 .current{border-color:#22c55e}.outdated{border-color:#ef4444}.unverifiable{border-color:#eab308}
 .score{float:right;font-weight:800;font-size:1.3em} a{color:#67e8f9} small{color:#94a3b8}
</style></head><body>
<h1>StaleCheck</h1>
<p class="sub">Paste an AI-generated answer. We find time-sensitive claims, re-check them on the live web, and score their freshness.</p>
<textarea id="a" placeholder="e.g. GPT-4 is OpenAI's latest model and costs $30 per million input tokens..."></textarea>
<button onclick="run()">Check freshness</button>
<div id="out"></div>
<script>
async function run(){
  const out=document.getElementById('out'); out.innerHTML='<p>Checking claims against the live web...</p>';
  const r=await fetch('/api/check',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({answer:document.getElementById('a').value})});
  const d=await r.json();
  if(d.error){out.innerHTML='<p style="color:#f87171">'+d.error+'</p>';return;}
  out.innerHTML=d.results.map(c=>`
   <div class="card ${c.status}">
     <span class="score">${c.freshness_score}/100</span>
     <b>${c.claim}</b><br><small>${c.category} &middot; ${c.status.toUpperCase()}</small>
     <p>${c.explanation||''}</p>
     ${c.correction?'<p><b>Current:</b> '+c.correction+'</p>':''}
     ${c.source_url?'<a href="'+c.source_url+'" target="_blank">Source</a>':''}
   </div>`).join('');
}
</script></body></html>
"""


@app.get("/")
def home():
    return render_template_string(PAGE)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
