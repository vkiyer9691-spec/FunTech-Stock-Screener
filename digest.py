"""Morning email digest: top-N picks per NSE universe.

Local preview writes HTML under digest_outbox/. Real SMTP send is optional
and skipped when SMTP_* is not configured.
"""

from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
PREFS_PATH = ROOT / "data" / "digest_prefs.json"
OUTBOX_DIR = ROOT / "digest_outbox"

QUICK_UNIVERSES = ["Nifty 50", "Nifty Next 50"]
DEFAULT_TOP_N = 10
DEFAULT_WEIGHTS = (4, 4, 2)


def _mail_cfg(name: str) -> str:
    env = str(os.environ.get(name) or "").strip()
    if env:
        return env
    try:
        import streamlit as st
        return str(st.secrets.get(name) or "").strip()
    except Exception:
        return ""


def is_smtp_configured() -> bool:
    return bool(_mail_cfg("SMTP_HOST") and _mail_cfg("SMTP_FROM"))


def is_weekday_ist(now: datetime | None = None) -> bool:
    ts = now.astimezone(IST) if now else datetime.now(IST)
    return ts.weekday() < 5


def load_all_prefs() -> dict:
    if not PREFS_PATH.exists():
        return {}
    try:
        return json.loads(PREFS_PATH.read_text())
    except Exception:
        return {}


def load_pref_for_user(user_id: str) -> dict:
    return load_all_prefs().get(str(user_id) or "", {})


DISCLAIMER = (
    "This is not a stock recommendation, and merely a ranking/scoring of stocks "
    "based on the user-selected settings and weightages. Before you invest your money, "
    "please do your own research and/or consult your financial advisor."
)


def normalize_settings(settings: dict | None) -> dict:
    settings = settings or {}
    w_fund = int(settings.get("w_fund", DEFAULT_WEIGHTS[0]))
    w_tech = int(settings.get("w_tech", DEFAULT_WEIGHTS[1]))
    w_rs = int(settings.get("w_rs", max(0, 10 - w_fund - w_tech)))
    fund_rules = dict(settings.get("fund_rules") or {})
    tech_rules = dict(settings.get("tech_rules") or {})
    rs_rules = dict(settings.get("rs_rules") or {})
    overrides = {}
    for prefix, rules in (("fund", fund_rules), ("tech", tech_rules), ("rs", rs_rules)):
        for key, val in rules.items():
            overrides[f"{prefix}_{key}"] = bool(val)
    return {
        "w_fund": w_fund,
        "w_tech": w_tech,
        "w_rs": w_rs,
        "fund_rules": fund_rules,
        "tech_rules": tech_rules,
        "rs_rules": rs_rules,
        "overrides": overrides,
    }


def save_pref(user_id: str, email: str, opt_in: bool, top_n: int, settings: dict | None = None) -> None:
    if not user_id:
        return
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = load_all_prefs()
    row = {
        "email": (email or "").strip(),
        "opt_in": bool(opt_in),
        "top_n": max(3, min(25, int(top_n or DEFAULT_TOP_N))),
        "updated_at": datetime.now(IST).isoformat(),
    }
    if settings:
        row.update({k: v for k, v in normalize_settings(settings).items() if k != "overrides"})
    else:
        existing = data.get(str(user_id)) or {}
        for key in ("w_fund", "w_tech", "w_rs", "fund_rules", "tech_rules", "rs_rules"):
            if key in existing:
                row[key] = existing[key]
    data[str(user_id)] = row
    PREFS_PATH.write_text(json.dumps(data, indent=2))


def subscriber_from_settings_row(row: dict, email: str) -> dict | None:
    if not email or not row.get("digest_opt_in"):
        return None
    return {
        "user_id": row.get("user_id"),
        "email": email.strip(),
        "opt_in": True,
        "top_n": max(3, min(25, int(row.get("digest_top_n") or DEFAULT_TOP_N))),
        "w_fund": row.get("w_fund", DEFAULT_WEIGHTS[0]),
        "w_tech": row.get("w_tech", DEFAULT_WEIGHTS[1]),
        "w_rs": row.get("w_rs", DEFAULT_WEIGHTS[2]),
        "fund_rules": row.get("fund_rules") or {},
        "tech_rules": row.get("tech_rules") or {},
        "rs_rules": row.get("rs_rules") or {},
    }


def _supabase_job_client():
    """Server-side client for the morning job. Prefer the service role so RLS
    does not hide other users' opt-in rows. Never put the service role in the
    Streamlit browser app — GitHub Actions secrets only."""
    try:
        from supabase import create_client
    except ImportError:
        return None
    url = _mail_cfg("SUPABASE_URL")
    key = _mail_cfg("SUPABASE_SERVICE_ROLE_KEY") or _mail_cfg("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def list_subscribers_from_supabase() -> list[dict]:
    client = _supabase_job_client()
    if not client:
        return []
    try:
        settings_res = client.table("user_settings").select("*").eq("digest_opt_in", True).execute()
    except Exception:
        return []
    emails = {}
    try:
        profiles_res = client.table("profiles").select("id,email").execute()
        for p in profiles_res.data or []:
            if p.get("id") and p.get("email"):
                emails[p["id"]] = p["email"]
    except Exception:
        pass
    subs = []
    for row in settings_res.data or []:
        uid = row.get("user_id")
        email = emails.get(uid) or row.get("email") or ""
        sub = subscriber_from_settings_row(row, email)
        if sub:
            subs.append(sub)
    return subs


def list_subscribers() -> list[dict]:
    cloud = list_subscribers_from_supabase()
    if cloud:
        return cloud
    subs = []
    for user_id, row in load_all_prefs().items():
        if row.get("opt_in") and row.get("email"):
            subs.append({"user_id": user_id, **row})
    return subs


def rank_universes(results_df: pd.DataFrame, universe_map: dict[str, list], top_n: int) -> list[dict]:
    sections = []
    if results_df is None or results_df.empty:
        for name in universe_map:
            sections.append({"universe": name, "tickers_scanned": 0, "rows": []})
        return sections

    scored = results_df.sort_values("Total Score", ascending=False)
    for name, tickers in universe_map.items():
        wanted = set(tickers)
        part = scored[scored["Ticker"].isin(wanted)].head(int(top_n))
        rows = []
        for _, r in part.iterrows():
            rows.append({
                "Ticker": r["Ticker"],
                "Total Score": float(r["Total Score"]),
                "Fundamental Score": float(r["Fundamental Score"]),
                "Technical Score": float(r["Technical Score"]),
                "Relative Strength Score": float(r["Relative Strength Score"]),
                "Sector": r.get("Sector", "Unknown"),
            })
        sections.append({
            "universe": name,
            "tickers_scanned": len(wanted),
            "rows": rows,
        })
    return sections


def render_html(sections: list[dict], generated_at: datetime, top_n: int, settings: dict | None = None) -> str:
    when = generated_at.astimezone(IST).strftime("%A, %d %b %Y, %H:%M IST")
    cfg = normalize_settings(settings)
    settings_line = (
        f"Your weights: Fundamental {cfg['w_fund']} / Technical {cfg['w_tech']} / "
        f"Relative Strength {cfg['w_rs']} (sum 10). Rankings use only the rules you have enabled."
    )
    blocks = []
    for sec in sections:
        rows_html = []
        if not sec["rows"]:
            rows_html.append("<tr><td colspan='7'>No scored tickers in this universe today.</td></tr>")
        else:
            for i, r in enumerate(sec["rows"], start=1):
                rows_html.append(
                    "<tr>"
                    f"<td>{i}</td>"
                    f"<td><strong>{r['Ticker']}</strong></td>"
                    f"<td>{r['Total Score']:.2f}</td>"
                    f"<td>{r['Fundamental Score']:.2f}</td>"
                    f"<td>{r['Technical Score']:.2f}</td>"
                    f"<td>{r['Relative Strength Score']:.2f}</td>"
                    f"<td>{r.get('Sector', '')}</td>"
                    "</tr>"
                )
        blocks.append(
            f"<h2>{sec['universe']}</h2>"
            f"<p style='color:#555'>Universe size {sec['tickers_scanned']}. Showing top {top_n} by total score.</p>"
            "<table cellpadding='8' cellspacing='0' border='1' style='border-collapse:collapse;width:100%;font-size:14px'>"
            "<thead><tr style='background:#111;color:#fff'>"
            "<th>#</th><th>Ticker</th><th>Total</th><th>Fund</th><th>Tech</th><th>RS</th><th>Sector</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FunTech morning picks</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#111">
  <h1>FunTech morning picks</h1>
  <p>Top {top_n} names in each NSE universe, scored with your current screener settings.</p>
  <p>{settings_line}</p>
  <p><strong>Generated:</strong> {when}</p>
  {''.join(blocks)}
  <p style="margin-top:36px;padding:16px;border:1px solid #ccc;background:#fafafa;font-size:13px;line-height:1.5">
    <strong>Disclaimer:</strong> {DISCLAIMER}
  </p>
  <p style="color:#666;font-size:12px">Markets open 9:15 AM IST. Educational use only.</p>
</body></html>
"""


def write_outbox(html: str, stamp: datetime | None = None) -> Path:
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = stamp or datetime.now(IST)
    path = OUTBOX_DIR / f"morning-digest-{ts.strftime('%Y-%m-%d-%H%M')}.html"
    path.write_text(html, encoding="utf-8")
    latest = OUTBOX_DIR / "latest.html"
    latest.write_text(html, encoding="utf-8")
    return path


def send_email(to_addr: str, subject: str, html: str) -> str:
    """Returns 'sent', 'skipped-no-smtp', or raises."""
    if not to_addr:
        return "skipped-no-recipient"
    if not is_smtp_configured():
        return "skipped-no-smtp"
    host = _mail_cfg("SMTP_HOST")
    port = int(_mail_cfg("SMTP_PORT") or "587")
    user = _mail_cfg("SMTP_USER")
    password = _mail_cfg("SMTP_PASSWORD")
    from_addr = _mail_cfg("SMTP_FROM")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.sendmail(from_addr, [to_addr], msg.as_string())
    return "sent"


def _universe_tickers(quick: bool) -> dict[str, list]:
    import app as screener

    names = QUICK_UNIVERSES if quick else list(screener.UNIVERSE_SOURCE_OPTIONS)
    out = {}
    for name in names:
        if quick:
            out[name] = list(screener.FALLBACK_INDEX_LISTS.get(name) or [])
            continue
        if name == "F&O Stocks":
            out[name] = screener.load_fo_stocks()
        else:
            out[name] = screener.load_index_list(name)
    return out


def _score_universe(screener, all_tickers, settings: dict, show_progress: bool):
    cfg = normalize_settings(settings)
    screener.set_score_overrides(cfg["overrides"])
    try:
        return screener.execute_scan(
            all_tickers, cfg["w_fund"], cfg["w_tech"], cfg["w_rs"], show_progress=show_progress
        )
    finally:
        screener.set_score_overrides(None)


def run_digest(
    *,
    quick: bool = False,
    send: bool = False,
    extra_recipients: list[str] | None = None,
    top_n: int = DEFAULT_TOP_N,
    skip_weekends: bool = False,
    now: datetime | None = None,
    settings: dict | None = None,
) -> dict:
    generated_at = now or datetime.now(IST)
    if skip_weekends and not is_weekday_ist(generated_at):
        return {
            "status": "skipped-weekend",
            "html": "",
            "outbox_path": None,
            "sections": [],
            "deliveries": [],
        }

    universe_map = _universe_tickers(quick=quick)
    all_tickers = list(dict.fromkeys(t for lst in universe_map.values() for t in lst))
    import app as screener

    subject = f"FunTech morning picks — {generated_at.strftime('%d %b %Y')}"
    deliveries = []

    if send:
        last_html = ""
        last_path = None
        last_sections = []
        skipped = []
        for sub in list_subscribers():
            sub_settings = normalize_settings(sub)
            sub_n = int(sub.get("top_n") or top_n)
            results_df, skipped = _score_universe(screener, all_tickers, sub_settings, show_progress=not quick)
            sections = rank_universes(results_df, universe_map, sub_n)
            html = render_html(sections, generated_at, sub_n, sub_settings)
            last_html, last_sections = html, sections
            last_path = write_outbox(html, generated_at)
            try:
                status = send_email(sub["email"], subject, html)
            except Exception as exc:
                status = f"error:{exc}"
            deliveries.append({"email": sub["email"], "status": status, "top_n": sub_n})
        for addr in extra_recipients or []:
            if last_html:
                try:
                    status = send_email(addr, subject, last_html)
                except Exception as exc:
                    status = f"error:{exc}"
                deliveries.append({"email": addr, "status": status})
        return {
            "status": "ok",
            "html": last_html,
            "outbox_path": str(last_path) if last_path else None,
            "sections": last_sections,
            "skipped_tickers": skipped,
            "ticker_count": len(all_tickers),
            "quick": quick,
            "smtp_configured": is_smtp_configured(),
            "deliveries": deliveries,
            "generated_at": generated_at.isoformat(),
        }

    cfg = normalize_settings(settings)
    results_df, skipped = _score_universe(screener, all_tickers, cfg, show_progress=not quick)
    sections = rank_universes(results_df, universe_map, top_n)
    html = render_html(sections, generated_at, top_n, cfg)
    outbox_path = write_outbox(html, generated_at)

    for addr in extra_recipients or []:
        try:
            status = send_email(addr, subject, html)
        except Exception as exc:
            status = f"error:{exc}"
        deliveries.append({"email": addr, "status": status})

    return {
        "status": "ok",
        "html": html,
        "outbox_path": str(outbox_path),
        "sections": sections,
        "skipped_tickers": skipped,
        "ticker_count": len(all_tickers),
        "quick": quick,
        "smtp_configured": is_smtp_configured(),
        "deliveries": deliveries,
        "generated_at": generated_at.isoformat(),
    }
