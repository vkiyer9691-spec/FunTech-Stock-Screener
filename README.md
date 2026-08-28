# FunTech Stock Screener

NSE stock screener for Indian equities. It scores tickers on customizable **fundamental**, **technical**, and **relative-strength** rules, evaluates broker holding files, and can export a TradingView watchlist.

This repo is the working copy of [vkiyer9691-spec/FunTech-Stock-Screener](https://github.com/vkiyer9691-spec/FunTech-Stock-Screener), imported so we can maintain and change it from Cursor Cloud Agents.

## What you can do

- Screen Nifty 50 / Next 50 / Midcap / Smallcap / 500 / F&O universes
- Toggle CANSLIM-style fundamental filters and a 10-point technical system
- Upload a broker holdings file and score the portfolio
- Sign in with Supabase for saved settings, watchlists, and scan history
- Use **Bypass Login (Developer / Local Mode)** when Supabase is not configured
- Opt in to a **weekday 8:30 AM IST email** of daily morning scores for each NSE index/group

## Run locally

Python 3.11+ recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 45127 --server.address 0.0.0.0
```

Open [http://127.0.0.1:45127](http://127.0.0.1:45127). On the login screen, either sign in or click **Bypass Login** to use the screener without a database.

## Optional: Supabase auth and persistence

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in:

- `SUPABASE_URL`
- `SUPABASE_KEY` (anon/public key)

Without those values, login, saved settings, watchlist, and scan history stay local-only. The screening engine still runs.

Do not commit `secrets.toml`.

## Daily morning scores

This was **not** in the Claude-generated GitHub snapshot. It is in this working copy:

1. In the sidebar, check **Email me weekday morning scores** and set **Number of stocks per group/index**.
2. Rankings use **your** pillar weights and enabled rules (saved when you opt in or change settings).
3. Click **Generate preview digest** (leave **Quick preview** on for a fast Nifty 50 + Next 50 sample).
4. Each email ends with a disclaimer that this is a score ranking, not a stock pick or recommendation.
5. The HTML is shown in the app and saved under `digest_outbox/`. SMTP is only needed for real inbox delivery.

```bash
python run_daily_digest.py --preview --quick
python run_daily_digest.py --send
```

GitHub Actions (`.github/workflows/morning-digest.yml`) is scheduled for **03:00 UTC (8:30 AM IST) Monday–Friday**. GitHub only queues that timer after it has indexed the workflow; a missed morning can be retried with **Run workflow**. A one-off cron at **03:50 UTC on 28 Aug (9:20 AM IST)** is included so 28 Aug 2026 can still send after the 8:30 slot was skipped.

To test delivery, use **Actions → Daily morning scores → Run workflow** on branch `main` (do not click **Re-run** on an old run — that replays the old commit). Leave **Quick preview** on, and optionally fill **Also send to this email**.

Required for inbox delivery:

- Repository secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- `SUPABASE_URL`, `SUPABASE_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` (service role, Actions only)
- Run `supabase_digest.sql` in the Supabase SQL editor, then opt in on **Streamlit Cloud** (not only a local Windows copy)
- Optional: `DIGEST_TO` if you want a copy even when opt-in lookup fails
- Replies are steered away from your Gmail via `Reply-To: noreply@funtech.invalid` (override with secret `SMTP_REPLY_TO`, or set it to `off` to keep replies on `SMTP_FROM`)

A green check with `"deliveries": []` means SMTP worked but **nobody was on the recipient list**. The job now fails in that case unless it can send a fallback copy to `SMTP_FROM`.

Local preferences are stored in `data/digest_prefs.json` as a fallback. Streamlit Cloud should keep using the **anon** key only.

## Project layout

| File | Role |
| --- | --- |
| `app.py` | Streamlit UI, scoring engine, NSE/Yahoo data fetchers |
| `digest.py` / `run_daily_digest.py` | Weekday daily morning scores email / HTML |
| `requirements.txt` | Python dependencies |
| `.devcontainer/` | GitHub Codespaces / VS Code container (Streamlit on port 8501) |
| `.streamlit/` | Server config and secrets example |

## Working with Cursor

Describe the change you want in chat (bug, filter, UI, data source). The agent edits this repo, runs the app, and you review the result in Preview.

Market data comes from Yahoo Finance and NSE public endpoints. Feeds can be delayed or blocked from some cloud IPs; the app falls back to a small built-in universe when live lists fail.

**Not financial advice.** Educational use only.
