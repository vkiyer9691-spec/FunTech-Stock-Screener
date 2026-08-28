# Scoring parameter audit

Working log of **intention vs code** for FunTech scores. Discuss and decide here; **one code change** after the set is agreed.

**Process**

1. For each rule: record copy (sidebar / help / User Guide), what classic CANSLIM meant, what the code actually does, Nifty 50 sample where it matters, and options.
2. You reply with a letter + option (e.g. `A2`, `N keep`) for everything you are ready to lock.
3. Implementation, tests, labels, and User Guide are updated **once** for all locked items (except **C2**, already shipped).
4. Do not ship scoring edits between letters unless you explicitly ask for a hotfix.

**How the pillar score works (not changing unless we say so)**

- Enabled fund/tech rules are pass/fail. Pillar = passes / evaluated × 10.
- Missing **fundamental** data is excluded from the denominator (not an auto-fail).
- Tech T1–T10 still count as fail if they cannot be computed.
- RS1/RS2 are continuous 0–5 each. Total = weighted mix; RS weight = `max(0, 10 − fund − tech)`, then divide by the actual weight sum.

---

## C — Current quarterly earnings

| Field | Value |
|---|---|
| **Status** | **Locked: C2 — already in `main`** |
| Sidebar | Current quarterly EPS vs same quarter last year > 15% |
| User Guide | Latest quarter vs same quarter last year; diluted EPS preferred, else net income; skip if missing; pass if > 15% |
| Classic CANSLIM C | This quarter EPS vs same quarter last year, often 18–25%+, sometimes with acceleration |
| Old code (C1) | Yahoo annual `earningsGrowth` won if present; else quarterly net income |
| **Agreed (C2)** | Latest quarter vs ~4 quarters back. Diluted EPS preferred, else net income. Skip if missing. Ignore `earningsGrowth`. Threshold stays **15%** (no acceleration). |
| Sample | 22/25 same as C1; BHARTIARTL & AXISBANK pass C1/fail C2; HCLTECH fail C1/pass C2 |
| Code | `canslim_c_growth()`, `fetch_info` sets `quarterly_eps_yoy` / `quarterly_ni_yoy` |

---

## A — Annual / sales growth

| Field | Value |
|---|---|
| **Status** | **Open — waiting on your pick** |
| Sidebar | Annual Revenue Growth > 10% |
| Help | Annual revenue growth must be above 10% |
| User Guide | Quarterly revenue growth > 10% YoY |
| Classic CANSLIM A | Annual **EPS** over years (often 25%+), not sales |
| **A1 (current)** | First quarterly row whose name contains `"revenue"` (often **Cost Of Revenue**), latest vs ~4 quarters back if year-ago > 0; else Yahoo `revenueGrowth` |
| Bug | Cost-of-goods matched before Total Revenue. Coal India A1 +125% costs vs +5% sales. Reliance A1 +23% costs vs +18% sales. |

**Options (Nifty 50 first 25, 28 Aug 2026 Yahoo)**

| ID | Rule | Pass | Fail | Skip | vs A1 |
|---|---|---:|---:|---:|---|
| A1 | Current (cost-of-revenue trap + Yahoo fallback) | 16 | 8 | 1 | — |
| **A2** | Quarterly **Total Revenue** YoY; skip if missing (C2-style). **Recommended.** | 14 | 9 | 2 | 23/25 |
| A3 | Yahoo `revenueGrowth` only (usually TTM/annual) | 18 | 6 | 1 | 21/25 |
| A4 | Latest full-year sales vs prior year > 10% | 9 | 15 | 1 | 14/25 |
| A5 | Annual diluted EPS > 25% (copybook A) | 5 | 19 | 1 | 12/25 |

A1 vs A2 diffs: **HDFCBANK** A1 pass (Yahoo annual) / A2 skip (only 3 quarterly columns); **COALINDIA** A1 pass / A2 fail. Tata Motors skip (Yahoo 404).

A2 matches the User Guide (quarterly sales), not the sidebar word “Annual”, and not O’Neil A (that is A5).

---

## N — New high / near high

| Field | Value |
|---|---|
| **Status** | Draft — not locked |
| Sidebar / UG | Near 52-week high (within 25%) |
| Classic N | New products/management **and/or** price making new highs (often within ~5–10% of the high, not 25%) |
| **Code** | `currentPrice` (Yahoo) or last close ≥ **75%** of Yahoo `fiftyTwoWeekHigh` (i.e. can be **25% off** the high). Skip if either missing. |
| Notes | 25% is a wide band: a stock 25% below the high still passes. High is Yahoo `year_high`, not always the true NSE 52-week high. |

**Options**

| ID | Rule |
|---|---|
| N1 | Keep: within 25% of 52-week high |
| N2 | Tighten to within **10%** of high |
| N3 | Tighten to within **5%** of high (closer to “new high”) |
| N4 | Use max of Yahoo high and the last 252 daily closes (fix stale/wrong Yahoo high) |

**Recommended discussion:** N1 vs N2, optionally plus N4 as a data fix on top of whichever band you want.

---

## S — Supply / demand (tight base)

| Field | Value |
|---|---|
| **Status** | Draft — not locked |
| Sidebar | Supply/Demand (Tight Base Consolidation) |
| Help / UG | 10-day volatility ≤ 6% **and** price near 50-DMA (code uses **within 5%** of 50-DMA) |
| Classic S | Small float / limited supply; demand showing in volume. Tightness is more of a chart setup. |
| **Code** | Needs ≥ 50 daily bars. `vol = std(close[-10]) / mean(close[-10]) * 100 ≤ 6` **and** `|close − SMA50| / SMA50 * 100 ≤ 5`. Skip if < 50 bars. Evaluated even if SMA50 is NaN (`near_50` becomes 99 → fail). |

**Options**

| ID | Rule |
|---|---|
| S1 | Keep current tightness rule (label already says base, not float) |
| S2 | Keep tightness; skip (don’t fail) when SMA50 is missing |
| S3 | Something else you specify (float is not in Yahoo reliably for NSE) |

**Recommended:** S1 behavior, S2 as a small missing-data fix aligned with C/A.

---

## L — Leader or laggard

| Field | Value |
|---|---|
| **Status** | Draft — not locked |
| Sidebar / UG | Leader RS: Daily RSI > 55 |
| Classic L | Leader = high **relative strength** vs the market (IBD RS 80+), not RSI |
| **Code** | 14-day RSI of daily close > 55. Skip if < 14 bars or RSI NaN. |
| Overlap | RS1/RS2 already score vs Nifty and sector. T7 is daily RSI > 50 and rising. L is a third RSI-ish check. |

**Options**

| ID | Rule |
|---|---|
| L1 | Keep RSI > 55 |
| L2 | Raise to RSI > 60 |
| L3 | Replace L with a pass/fail on RS vs Nifty (e.g. 63-day return > benchmark) — overlaps RS1 |
| L4 | Drop L from fundamentals (leadership lives in the RS pillar) |

**Recommended discussion:** L1 unless you want L to mean true RS (then L3 or L4).

---

## I — Institutional sponsorship

| Field | Value |
|---|---|
| **Status** | Draft — not locked |
| Sidebar / UG | Institutional ownership > 30% |
| Help | Data is often missing |
| Classic I | Quality funds increasing positions; not just a static % |
| **Code** | Yahoo `heldPercentInstitutions` > 0.30. Skip if missing. |
| Notes | For many NSE names this field is empty or US-shareholder-oriented. Skipping missing data avoids a mass fail, but then I barely affects Nifty scores. |

**Options**

| ID | Rule |
|---|---|
| I1 | Keep > 30% when Yahoo has it; skip when missing |
| I2 | Keep but treat missing as fail |
| I3 | Drop I until we have an NSE holdings source |

**Recommended:** I1 until a better India source exists.

---

## M — Market direction

| Field | Value |
|---|---|
| **Status** | Draft — not locked |
| Sidebar / UG | Nifty 50 above its 200-DMA |
| Classic M | Don’t fight the general market; often index vs 50/200-DMA plus distribution days |
| **Code** | `^NSEI` last close > SMA200. Skip if < 200 bars. **Same pass/fail for every stock in a scan.** |
| Notes | When M fails, every name loses the same fundamental point. When it passes, everyone gets it. It does not rank stocks; it times the tape. |

**Options**

| ID | Rule |
|---|---|
| M1 | Keep Nifty > 200-DMA |
| M2 | Nifty > 200-DMA **and** 200-DMA sloping up (5 bars), like T4 |
| M3 | Drop M from per-stock score; show market regime as a banner only |

**Recommended:** M1 unless you want M to be stricter (M2) or informational (M3).

---

## T1–T10 — Technical (not discussed yet)

All are pass/fail. Missing data **fails** (unlike fundamentals). Need ≥ 30 daily bars or the whole pillar is 0.

| ID | Label | Code | Status |
|---|---|---|---|
| T1 | Close > 200 DMA and near 50 DMA (within 5%) | `close > SMA200` and `|close−SMA50|/SMA50 ≤ 5%` | Open |
| T2 | Tight consolidation near 50/20 DMA | (`near 50` or `near 20` within 5%) and 10-day vol ≤ 6% | Open |
| T3 | Early Stage 2: Close ≤ 1.25 × 200 DMA | `SMA200 < close ≤ 1.25×SMA200` | Open |
| T4 | 50 and 200 DMA sloping up (5 bars) | last > value 5 bars ago on each SMA | Open |
| T5 | Monthly RSI > 50 and rising | monthly RSI last > 50 and last > 2 bars ago | Open |
| T6 | Weekly RSI > 50 and rising | same on weekly | Open |
| T7 | Daily RSI > 50 and rising | same on daily (overlaps L’s RSI > 55) | Open |
| T8 | Monthly MACD line rising | MACD line last > 2 bars ago | Open |
| T9 | Weekly MACD positive crossover and rising | MACD > signal, MACD > 0, line rising | Open |
| T10 | Daily MACD line rising | line rising | Open |

`slope_up` / `is_rising` compare **two points** (now vs N bars ago), not a fitted slope.

---

## RS1 / RS2 — Relative strength (not discussed yet)

| ID | Label | Code | Status |
|---|---|---|---|
| RS1 | vs Nifty 50, ~63 trading days | `clip(2.5 + (stock−nifty)% / 10 × 2.5, 0, 5)` so ±10pp vs Nifty maps to 0–5 | Open |
| RS2 | vs same-sector peers **in this scan** | Same formula vs sector average 63-day return. Skipped if sector missing/Unknown. | Open |

RS2 is scan-universe dependent: a Nifty 50-only scan uses only those peers, not the whole sector.

---

## Locked decisions (implement in the next scoring batch)

- **C2** — already in production code.

## Pending your reply

- **A** — A1 / A2 / A3 / A4 / A5
- **N, S, L, I, M** — pick IDs above or “keep”
- Then T1–T10 and RS1/RS2 in a later pass of this same file, still one implementation drop
