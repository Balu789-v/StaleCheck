# StaleCheck: Stale-Answer Detector for AI Applications

LLMs often state facts that were true once but are now outdated (pricing, API versions, laws, leadership).
StaleCheck takes an LLM-generated answer, finds the time-sensitive claims, re-verifies each one against
the live web, and gives every claim a **freshness score (0-100)** with a correction and source link.

## How it works
1. **Claim identification:** an LLM extracts time-sensitive factual claims and writes a search query for each.
2. **Live verification:** each claim is searched with **Tavily**.
3. **Freshness detection and scoring:** an LLM compares the claim to the Tavily sources only
   (no guessing) and returns `current`, `outdated`, or `unverifiable`, plus a 0-100 score.

## How each technology is used
- **Tavily:** live web search and source retrieval that re-checks every claim against current information.
- **Bifrost (Maxim AI):** all LLM requests (claim extraction and judging) go through the Bifrost gateway
  using its OpenAI-compatible API. This gives provider routing, failover, and request logging in the Bifrost dashboard.

## Setup
```bash
git clone <your-repo-url> && cd stalecheck
pip install -r requirements.txt
cp .env.example .env          # add your TAVILY_API_KEY

# Terminal 1: start Bifrost, open http://localhost:8080 and add a provider key
npx -y @maximhq/bifrost

# Terminal 2: run the app
python app.py                 # open http://localhost:5000
```

## Demo input
> GPT-4 is OpenAI's newest model and costs $30 per million input tokens. Python 3.9 is the latest Python
> version. The CEO of Twitter is Jack Dorsey.

## Tech stack
Python, Flask, Tavily API, Bifrost gateway, OpenAI-compatible LLM.
