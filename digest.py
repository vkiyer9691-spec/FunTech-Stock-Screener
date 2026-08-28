"""Daily email of top scores per NSE index/group.

Local preview writes HTML under digest_outbox/. Real SMTP send is optional
and skipped when SMTP_* is not configured.
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
PREFS_PATH = ROOT / "data" / "digest_prefs.json"
OUTBOX_DIR = ROOT / "digest_outbox"

QUICK_UNIVERSES = ["Nifty 50", "Nifty Next 50"]
DEFAULT_TOP_N = 10
DEFAULT_WEIGHTS = (5, 5)
DEFAULT_FROM_NAME = "FunTech Screener"
DIGEST_TITLE = "FunTech top scores"
# Reserved .invalid TLD — replies bounce instead of landing in SMTP_FROM.
DEFAULT_REPLY_TO_ADDR = "noreply@funtech.invalid"


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


def clamp_pillar_weights(w_fund, w_tech, w_rs=None) -> tuple[int, int]:
    """Two pillars that always sum to 10. w_rs is ignored (legacy settings)."""
    try:
        w_fund = int(w_fund or 0)
    except (TypeError, ValueError):
        w_fund = 0
    try:
        w_tech = int(w_tech or 0)
    except (TypeError, ValueError):
        w_tech = 0
    w_fund = max(0, min(10, w_fund))
    w_tech = max(0, min(10, w_tech))
    total = w_fund + w_tech
    if total <= 0:
        return 5, 5
    if total != 10:
        w_fund = int(round(w_fund * 10 / total))
        w_fund = max(0, min(10, w_fund))
        w_tech = 10 - w_fund
    return w_fund, w_tech


def weighted_total(fund_score: float, tech_score: float, w_fund: int, w_tech: int) -> float:
    denom = w_fund + w_tech
    if denom <= 0:
        return 0.0
    return (fund_score * w_fund + tech_score * w_tech) / denom


def normalize_settings(settings: dict | None) -> dict:
    settings = settings or {}
    w_fund, w_tech = clamp_pillar_weights(
        settings.get("w_fund", DEFAULT_WEIGHTS[0]),
        settings.get("w_tech", DEFAULT_WEIGHTS[1]),
    )
    fund_rules = dict(settings.get("fund_rules") or {})
    tech_rules = dict(settings.get("tech_rules") or {})
    overrides = {}
    for prefix, rules in (("fund", fund_rules), ("tech", tech_rules)):
        for key, val in rules.items():
            overrides[f"{prefix}_{key}"] = bool(val)
    return {
        "w_fund": w_fund,
        "w_tech": w_tech,
        "fund_rules": fund_rules,
        "tech_rules": tech_rules,
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
        for key in ("w_fund", "w_tech", "fund_rules", "tech_rules"):
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
        **{k: v for k, v in normalize_settings(row).items() if k != "overrides"},
    }


def _log(msg: str) -> None:
    print(f"digest: {msg}", file=sys.stderr, flush=True)


def extract_email_address(raw: str) -> str:
    _name, addr = parseaddr((raw or "").strip())
    if addr and "@" in addr:
        return addr
    text = (raw or "").strip()
    if "<" in text and ">" in text:
        text = text.split("<", 1)[1].split(">", 1)[0].strip()
    return text if "@" in text else ""


def smtp_from_parts() -> tuple[str, str]:
    """Display From header and envelope mailbox for SMTP."""
    raw = _mail_cfg("SMTP_FROM")
    _ignored_name, addr = parseaddr(raw)
    addr = addr or extract_email_address(raw)
    name = (_mail_cfg("SMTP_FROM_NAME") or DEFAULT_FROM_NAME).strip()
    if not addr:
        return raw, ""
    return formataddr((name, addr)), addr


def smtp_reply_to_header() -> str:
    """Reply-To so clients do not default to the Gmail From address.

    Set SMTP_REPLY_TO to off/none/- to leave replies on SMTP_FROM.
    """
    raw = _mail_cfg("SMTP_REPLY_TO")
    if raw.lower() in {"off", "none", "-", "from"}:
        return ""
    if not raw:
        return formataddr((DEFAULT_FROM_NAME, DEFAULT_REPLY_TO_ADDR))
    name, addr = parseaddr(raw)
    addr = addr or extract_email_address(raw)
    if not addr:
        return ""
    return formataddr((name or DEFAULT_FROM_NAME, addr))


def extra_recipients_from_env(explicit: list[str] | None = None) -> list[str]:
    seen: list[str] = []
    for item in list(explicit or []) + [part.strip() for part in (_mail_cfg("DIGEST_TO") or "").split(",")]:
        addr = extract_email_address(item)
        if addr and addr.lower() not in {s.lower() for s in seen}:
            seen.append(addr)
    return seen


def _supabase_job_client():
    """Server-side client for the morning job. Prefer the service role so RLS
    does not hide other users' opt-in rows. Never put the service role in the
    Streamlit browser app — GitHub Actions secrets only."""
    try:
        from supabase import create_client
    except ImportError:
        _log("supabase package is not installed")
        return None
    url = _mail_cfg("SUPABASE_URL")
    key = _mail_cfg("SUPABASE_SERVICE_ROLE_KEY") or _mail_cfg("SUPABASE_KEY")
    if not url or not key:
        _log("no SUPABASE_URL / key for subscriber lookup")
        return None
    if not _mail_cfg("SUPABASE_SERVICE_ROLE_KEY"):
        _log("SUPABASE_SERVICE_ROLE_KEY is missing; anon key may be blocked by RLS")
    try:
        return create_client(url, key)
    except Exception as exc:
        _log(f"could not create Supabase client: {exc}")
        return None


def _emails_by_user_id(client) -> dict:
    emails: dict = {}
    try:
        profiles_res = client.table("profiles").select("id,email").execute()
        for p in profiles_res.data or []:
            if p.get("id") and p.get("email"):
                emails[p["id"]] = p["email"]
        _log(f"profiles rows with email: {len(emails)}")
    except Exception as exc:
        _log(f"profiles lookup failed: {exc}")
    if _mail_cfg("SUPABASE_SERVICE_ROLE_KEY"):
        try:
            listed = client.auth.admin.list_users()
            users = getattr(listed, "users", None)
            if users is None:
                users = listed if isinstance(listed, list) else []
            added = 0
            for user in users or []:
                uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
                email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
                if uid and email and uid not in emails:
                    emails[uid] = email
                    added += 1
            _log(f"auth.admin emails added: {added}")
        except Exception as exc:
            _log(f"auth.admin list_users failed: {exc}")
    return emails


def list_subscribers_from_supabase() -> list[dict]:
    client = _supabase_job_client()
    if not client:
        return []
    try:
        settings_res = client.table("user_settings").select("*").eq("digest_opt_in", True).execute()
    except Exception as exc:
        _log(f"user_settings digest_opt_in query failed: {exc}")
        return []
    opted_in = list(settings_res.data or [])
    _log(f"user_settings opted-in rows: {len(opted_in)}")
    emails = _emails_by_user_id(client)
    subs = []
    missing_email = 0
    for row in opted_in:
        uid = row.get("user_id")
        email = emails.get(uid) or row.get("email") or ""
        sub = subscriber_from_settings_row(row, email)
        if sub:
            subs.append(sub)
        else:
            missing_email += 1
    if missing_email:
        _log(f"opted-in rows skipped (no email): {missing_email}")
    return subs


def list_subscribers() -> list[dict]:
    cloud = list_subscribers_from_supabase()
    if cloud:
        _log(f"using {len(cloud)} Supabase subscriber(s)")
        return cloud
    subs = []
    for user_id, row in load_all_prefs().items():
        if row.get("opt_in") and row.get("email"):
            subs.append({"user_id": user_id, **row})
    _log(f"Supabase returned nobody; local digest_prefs.json subscribers: {len(subs)}")
    return subs


def tradingview_symbols(sections: list[dict], min_score: float = 0.0) -> list[str]:
    """Unique NSE:TICKER strings from top-score rows, highest Total Score first.

    A name that ranks in more than one index (e.g. Nifty 50 and Nifty 500) appears once.
    """
    best: dict[str, float] = {}
    for sec in sections or []:
        for row in sec.get("rows") or []:
            ticker = row.get("Ticker")
            if not ticker:
                continue
            try:
                score = float(row.get("Total Score") or 0)
            except (TypeError, ValueError):
                score = 0.0
            if score < float(min_score):
                continue
            prev = best.get(ticker)
            if prev is None or score > prev:
                best[ticker] = score
    ordered = sorted(best.items(), key=lambda item: item[1], reverse=True)
    return [f"NSE:{ticker.replace('.NS', '')}" for ticker, _score in ordered]


def tradingview_watchlist(sections: list[dict], min_score: float = 0.0) -> str:
    return ",".join(tradingview_symbols(sections, min_score))


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
    weight_sum = cfg["w_fund"] + cfg["w_tech"]
    settings_line = (
        f"Your weights: Fundamental {cfg['w_fund']} / Technical {cfg['w_tech']} "
        f"(sum {weight_sum}). Rankings use only the rules you have enabled."
    )
    blocks = []
    for sec in sections:
        rows_html = []
        if not sec["rows"]:
            rows_html.append("<tr><td colspan='6'>No scored tickers in this universe today.</td></tr>")
        else:
            for i, r in enumerate(sec["rows"], start=1):
                rows_html.append(
                    "<tr>"
                    f"<td>{i}</td>"
                    f"<td><strong>{r['Ticker']}</strong></td>"
                    f"<td>{r['Total Score']:.2f}</td>"
                    f"<td>{r['Fundamental Score']:.2f}</td>"
                    f"<td>{r['Technical Score']:.2f}</td>"
                    f"<td>{r.get('Sector', '')}</td>"
                    "</tr>"
                )
        blocks.append(
            f"<h2>{sec['universe']}</h2>"
            f"<p style='color:#555'>Index/group size {sec['tickers_scanned']}. Showing {top_n} stocks by total score.</p>"
            "<table cellpadding='8' cellspacing='0' border='1' style='border-collapse:collapse;width:100%;font-size:14px'>"
            "<thead><tr style='background:#111;color:#fff'>"
            "<th>#</th><th>Ticker</th><th>Total</th><th>Fund</th><th>Tech</th><th>Sector</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody></table>"
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{DIGEST_TITLE}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#111">
  <h1>{DIGEST_TITLE}</h1>
  <p>Highest-scoring {top_n} stocks in each NSE index/group, scored with your current screener settings. This is a ranking of scores, not a stock pick or recommendation. Sent once every day.</p>
  <p>{settings_line}</p>
  <p><strong>Generated:</strong> {when}</p>
  {''.join(blocks)}
  <p style="margin-top:36px;padding:16px;border:1px solid #ccc;background:#fafafa;font-size:13px;line-height:1.5">
    <strong>Disclaimer:</strong> {DISCLAIMER}
  </p>
  <p style="color:#666;font-size:12px">This message is sent automatically. Replies are not delivered to the sender.</p>
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
    from_header, envelope_from = smtp_from_parts()
    envelope_from = envelope_from or extract_email_address(_mail_cfg("SMTP_FROM"))
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = to_addr
    reply_to = smtp_reply_to_header()
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.sendmail(envelope_from, [to_addr], msg.as_string())
    return "sent"


def _screener_mod():
    """The scoring module Streamlit already loaded, or a fresh import of app.py.

    `streamlit run app.py` executes the file as `__main__`. A second `import app`
    can bind a half-initialized module (circular import) that is missing
    `set_score_overrides`, which is what Show top scores hits.
    """
    import sys

    needed = (
        "set_score_overrides",
        "execute_scan",
        "UNIVERSE_SOURCE_OPTIONS",
        "FALLBACK_INDEX_LISTS",
        "load_fo_stocks",
        "load_index_list",
    )
    for name in ("__main__", "app"):
        mod = sys.modules.get(name)
        if mod is not None and all(hasattr(mod, attr) for attr in needed):
            return mod
    import app as screener
    return screener


def _universe_tickers(quick: bool) -> dict[str, list]:
    screener = _screener_mod()

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
            all_tickers, cfg["w_fund"], cfg["w_tech"], show_progress=show_progress
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
    screener = _screener_mod()

    subject = f"{DIGEST_TITLE} — {generated_at.strftime('%d %b %Y')}"
    deliveries = []
    extras = extra_recipients_from_env(extra_recipients)
    used_smtp_from_fallback = False

    if send:
        last_html = ""
        last_path = None
        last_sections = []
        skipped = []
        subscribers = list_subscribers()
        if not subscribers and not extras:
            fallback = extract_email_address(_mail_cfg("SMTP_FROM"))
            if fallback:
                extras = [fallback]
                used_smtp_from_fallback = True
                _log(f"no opted-in subscribers; sending a fallback copy to SMTP_FROM ({fallback})")
        if not subscribers and not extras:
            cfg = normalize_settings(settings)
            results_df, skipped = _score_universe(screener, all_tickers, cfg, show_progress=not quick)
            last_sections = rank_universes(results_df, universe_map, top_n)
            last_html = render_html(last_sections, generated_at, top_n, cfg)
            last_path = write_outbox(last_html, generated_at)
            _log("nobody to email. Opt in on Streamlit Cloud, run supabase_digest.sql, and add SUPABASE_SERVICE_ROLE_KEY.")
            return {
                "status": "no-subscribers",
                "html": last_html,
                "outbox_path": str(last_path) if last_path else None,
                "sections": last_sections,
                "skipped_tickers": skipped,
                "ticker_count": len(all_tickers),
                "quick": quick,
                "smtp_configured": is_smtp_configured(),
                "deliveries": [],
                "used_smtp_from_fallback": False,
                "generated_at": generated_at.isoformat(),
            }
        for sub in subscribers:
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
        if extras and not last_html:
            cfg = normalize_settings(settings)
            results_df, skipped = _score_universe(screener, all_tickers, cfg, show_progress=not quick)
            last_sections = rank_universes(results_df, universe_map, top_n)
            last_html = render_html(last_sections, generated_at, top_n, cfg)
            last_path = write_outbox(last_html, generated_at)
        sent_already = {d["email"].lower() for d in deliveries}
        for addr in extras:
            if addr.lower() in sent_already or not last_html:
                continue
            try:
                status = send_email(addr, subject, last_html)
            except Exception as exc:
                status = f"error:{exc}"
            deliveries.append({"email": addr, "status": status, "fallback": used_smtp_from_fallback})
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
            "used_smtp_from_fallback": used_smtp_from_fallback,
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
