# Scoring parameter audit

Working log of **intention vs code** for FunTech scores. Discuss and decide here; **one code change** after the set is agreed.

**Process**

1. For each rule: record copy (sidebar / help / User Guide), what classic CANSLIM meant, what the code actually does, Nifty 50 sample where it matters, and options.
2. You reply with a letter + option (e.g. `A2`, `N keep`) for everything you are ready to lock.
3. Implementation, tests, labels, and User Guide were updated in one scoring batch (`8351a51` on GitHub `main`), except **C2** which shipped earlier. T1–T10 were then reviewed in groups and left as coded.
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
| **Status** | **Locked: A2 — in `main`** |
| Sidebar | Annual Revenue Growth > 10% *(will be relabeled to quarterly Total Revenue)* |
| Help | Annual revenue growth must be above 10% |
| User Guide | Quarterly revenue growth > 10% YoY |
| Classic CANSLIM A | Annual **EPS** over years (often 25%+), not sales |
| **A1 (current)** | First quarterly row whose name contains `"revenue"` (often **Cost Of Revenue**), latest vs ~4 quarters back if year-ago > 0; else Yahoo `revenueGrowth` |
| Bug | Cost-of-goods matched before Total Revenue. Coal India A1 +125% costs vs +5% sales. Reliance A1 +23% costs vs +18% sales. |
| **Agreed (A2)** | Latest quarter **Total Revenue** vs ~4 quarters back (same helper as C2). Skip if missing. No Yahoo `revenueGrowth` fallback. Threshold stays **10%**. Relabel so it does not say “Annual”. |

**Options (Nifty 50 first 25, 28 Aug 2026 Yahoo)** — A2 chosen

| ID | Rule | Pass | Fail | Skip | vs A1 |
|---|---|---:|---:|---:|---|
| A1 | Current (cost-of-revenue trap + Yahoo fallback) | 16 | 8 | 1 | — |
| **A2** | Quarterly **Total Revenue** YoY; skip if missing | 14 | 9 | 2 | 23/25 |
| A3 | Yahoo `revenueGrowth` only (usually TTM/annual) | 18 | 6 | 1 | 21/25 |
| A4 | Latest full-year sales vs prior year > 10% | 9 | 15 | 1 | 14/25 |
| A5 | Annual diluted EPS > 25% (copybook A) | 5 | 19 | 1 | 12/25 |

A1 vs A2 diffs: **HDFCBANK** A1 pass (Yahoo annual) / A2 skip (only 3 quarterly columns); **COALINDIA** A1 pass / A2 fail. Tata Motors skip (Yahoo 404).

A2 is consistent with C2. It is still **sales**, not copybook A (annual EPS).

---

## N — New (products, management, highs)

| Field | Value |
|---|---|
| **Status** | **Locked: N2 + N4 — in `main`** |
| Sidebar / UG | Near 52-week high (within 25%) |
| Classic N | See below. Quantitative half = **new price highs**, not “25% off the high”. |
| **Code (N1)** | `currentPrice` (Yahoo fast_info / info) or last close ≥ **75%** of Yahoo `fiftyTwoWeekHigh`. Skip if high or price missing. |
| Data | On 28 Aug 2026 this environment’s `fast_info.year_high` was empty for all 25 sample names, so N would skip unless `t.info` fills `fiftyTwoWeekHigh`. Daily bars still have a usable 52-week high. |

**What O’Neil’s N actually is**

N is **New**: new products or services that drive a step-change in earnings, new management, and/or **new price highs**. The investable expression on the chart is a stock leaving a base and making (or sitting right under) a 52-week high — “buy high, sell higher.” He did not mean “the stock is merely not in a collapse.” Constructive pullbacks in that system are often on the order of **8–12%** from the high, sometimes ~15% in a deeper but still valid base. **25% off** is usually “wide and loose” / a failed move, not a new-high leader.

We only code the **price** half. New products and new management are qualitative and stay out of the score unless we add a manual flag later.

**Is the current rule a decent proxy?**

It is a **weak, one-sided proxy**. Directionally it drops deep laggards (IT/FMCG names ~26–34% below the 1-year high on this sample). It does **not** require a new high, a breakout, or even “near” the high. At 25%, it behaves more like “still in a broad uptrend / not a wreck” than CANSLIM N.

Nifty 50 first 25, **distance from max daily high over ~1 year** (Yahoo `year_high` missing here):

| Band | Pass | Fail | Skip | Who |
|---|---:|---:|---:|---|
| **25% (current N1)** | 19 | 5 | 1 | Fails: INFY, ITC, TCS, HDFCBANK, HUL (HUL only just: 25.8%) |
| **10% (N2)** | 8 | 16 | 1 | Pass e.g. TITAN, ICICI, ADANIENT, SUNPHARMA, KOTAK, LT, BAJFINANCE, BAJAJFINSV |
| **5% (N3)** | 3 | 21 | 1 | TITAN ~0.7%, ICICI ~2.4%, ADANIENT ~2.7% |

So 25% passes **~4 in 5** large caps; 10% passes **~1 in 3**; 5% is a true “near high” filter.

**N4** (high = max(Yahoo high, last 252 daily highs)) is a **data fix**, not a tightness choice. It can be stacked on N1/N2/N3. Recommended if we keep any near-high rule, because Yahoo `year_high` is unreliable here.

**Options**

| ID | Rule |
|---|---|
| N1 | Keep: within 25% of 52-week high (laggard filter, not really N) |
| N2 | Within **10%** of high (closer to IBD-style “near high” screens) |
| N3 | Within **5%** of high (strict near-new-high) |
| N4 | Compute high from daily bars (optionally merge Yahoo). Stack on N1/N2/N3 |
| N5 | Pass only if last close is within X% **or** the 52-week high occurred in the last N days (recent new high) |

**Agreed:** **N2 + N4** — last close within **10%** of the 52-week high, high = max of Yahoo (if present) and the last ~252 daily highs. Relabel off “within 25%”.

---

## S — Supply and demand

| Field | Value |
|---|---|
| **Status** | **Locked: S3, 20 trading days — in `main`** |
| Sidebar | Supply/Demand (Tight Base Consolidation) |
| Help / UG | 10-day volatility ≤ 6% **and** price near 50-DMA (code: within **5%** of 50-DMA) |
| **Code (S1)** | Needs ≥ 50 daily bars. Pass if 10-day close std/mean ≤ 6% **and** \|close − SMA50\| / SMA50 ≤ 5%. Skip if < 50 bars. If SMA50 is NaN, distance is set to 99 → **fail** (not skip). |

**What O’Neil’s S actually is**

S is **Supply and Demand**. He wanted **limited supply** (smaller float / fewer shares out, buybacks, big insider ownership) so that **institutional demand** could lift the price. Demand shows up as **volume**: heavier volume on up days than down days (accumulation), not a quiet, low-volatility coil. A huge share count or a dilutive offering is a negative.

A **tight base** (narrow price, low vol, coiled near MAs) is a real O’Neil chart idea, but it belongs with the **buy point / N**, not with the letter S. Our label mixes the two.

**What the code does**

It is a **tightness + “hugging the 50-DMA”** test. It does not use float, share count, buybacks, or up/down volume. It overlaps **T1** (near 50-DMA) and **T2** (tight coil near 50/20-DMA).

On the first 25 Nifty 50 names (28 Aug 2026 daily bars):

| Check | Pass | Fail | Skip |
|---|---:|---:|---:|
| **S1 (vol ≤ 6% and within 5% of 50-DMA)** | 20 | 4 | 1 |
| 10-day vol ≤ 6% alone | 24 | 0 | 1 |
| Within 5% of 50-DMA alone | 20 | 4 | 1 |
| Same but vol ≤ 4% | 20 | 4 | 1 |

The vol ≤ 6% clause **never failed** this sample (highest 10-day vol was Kotak ~3.4%). Every S1 fail was **distance from the 50-DMA**: HDFC Bank 6.5%, HUL 5.1%, Kotak 8.2%, Titan 8.2%. Tata Motors skip (no Yahoo daily).

Yahoo `floatShares` **was** present for 24/25 names here (Maruti ~116M vs HDFC Bank ~15B). A true small-float rule would still fail almost all Nifty 50 names; it would only start to matter in small/midcap scans.

**Options**

| ID | Rule |
|---|---|
| **S1** | Keep current: vol ≤ 6% and within 5% of 50-DMA. Honest label: tight base, not supply/demand |
| **S1b** | S1 plus skip (don’t fail) when SMA50 is missing |
| **S2** | Drop the inert vol clause; pass iff within 5% of 50-DMA (same Nifty 50 result as S1 today) |
| **S3** | True-S demand proxy: last 20 sessions’ up-volume > down-volume. Different names will pass |
| **S4** | True-S supply proxy: float below a cap (only useful outside Nifty 50; threshold TBD) |
| **S5** | Drop S from fundamentals; tightness already lives in T1/T2 |

**Would S3 be a good alternative?** **Yes**, if S is allowed to mean **demand (accumulation)**, not float. T1/T2 already score tightness, so keeping S1 would double-count a chart coil and still ignore volume.

S3 is still only **half** of O’Neil S (demand, not small supply). That is the half we can measure on NSE Yahoo data. Relabel to volume/demand, not “tight base.”

**Proposed spec (S3):** using daily bars, sum volume on days the **close is up** vs days the close is down. Pass if up-volume > down-volume. Skip if volume is missing or there are not enough bars. Unchanged closes are ignored (not counted as up or down).

**Lookback on the same 24 names (Tata Motors skip):**

| Rule | Pass | Fail | vs S1 |
|---|---:|---:|---|
| S1 tightness (current) | 20 | 4 | — |
| **S3, 20 sessions, ratio > 1** | 10 | 14 | same on only 10/24 |
| **S3, 50 sessions, ratio > 1** | 14 | 10 | same on 14/24 |
| S3, 20 sessions, ratio > 1.2 | 6 | 18 | very strict |

20 days is noisy (TCS fails 20d / passes 50d; Infosys and L&T the reverse). **50 sessions** is the better default: same length as the 50-DMA we already compute, less twitchy.

Names tightness and volume **disagree** on (50d): Kotak and Titan **fail S1 / pass S3** (weak coil, but buyers have been more active). Reliance, ITC, L&T, Axis, NTPC, Power Grid **pass S1 / fail S3** (quiet near the 50-DMA, but more volume on down days).

**Agreed (S3, 20 days):** Last **20** sessions: sum volume on up-close days vs down-close days. Pass if up-volume > down-volume. Skip if volume or bars missing. Flat closes ignored. Relabel as demand / accumulation (not tight base). Tightness stays on **T1/T2**. Do not keep S1.

You chose 20 days over 50 knowing it is jumpy. On the sample that is **10 pass / 14 fail**.

---

## L — Leader or laggard

| Field | Value |
|---|---|
| **Status** | **Locked: L9a — fold RS into L, drop RS pillar. In `main`** |
| Sidebar / UG | Leader RS: Daily RSI > 55 |
| **Code (L1)** | 14-day RSI of daily close > 55. Skip if < 14 bars or RSI is NaN. |

**What O’Neil’s L actually is**

L is **Leader or Laggard**. He wanted stocks that are **already leading the market**, not cheap laggards “about to catch up.” IBD expressed that as a **Relative Strength rating** (leaders often 80–90+ vs the rest of the exchange). That is **price vs the market over months**, not an oscillator.

RSI > 55 only says the name has been bid up over ~14 days. A leader can have RSI 40 after a short rest; a laggard can have RSI 70 on a dead-cat bounce.

**Overlap**

- **T7:** daily RSI > **50** and **rising** — almost the same oscillator.
- **RS1:** 63-day return vs Nifty, scored 0–5 continuously. That *is* classical L, already in another pillar.

**Nifty 50 first 25 (28 Aug 2026):**

| Rule | Pass | Fail | Skip |
|---|---:|---:|---:|
| **L1 RSI > 55 (current)** | 3 | 21 | 1 |
| L2 RSI > 60 | 3 | 21 | 1 |
| T7 RSI > 50 and rising | 6 | 18 | 1 |
| **L3 63-day return > Nifty** | 13 | 11 | 1 |

L1 passers: only **Kotak (RSI 76), Titan (71), Adani Ent (65)** — all also beat Nifty. L1 vs T7 matched **21/24** (TCS, Infosys, Axis pass T7, fail L1). L1 vs true RS (L3) matched only **14/24**: ten names **beat Nifty** but fail RSI 55 (ICICI, SBI, Bajaj Finance, M&M, Sun Pharma, …).

So L1 is a **strict short-term momentum cut**, not “leader vs laggard.” In this tape it almost never passes.

**Options**

| ID | Rule |
|---|---|
| L1 | Keep RSI > 55 (strict; duplicates T7’s family) |
| L2 | RSI > 60 (same 3 names here) |
| **L3** | Pass if 63-day return > Nifty (binary cousin of RS1) |
| L4 | Drop L from fundamentals; leadership stays in RS1/RS2 |
| L5 | Keep L1 but raise T7’s role only — not recommended |

**Recommended:** **L4** if you do not want two copies of leadership, or **L3** if you want a pass/fail “beats the market” point in the CANSLIM pillar and are fine that RS1 still scores the *amount* of outperformance. I would **not** keep RSI as L.

**Your reading (overlap with RS) is right.** Classical L *is* relative strength vs the market. **RS1** is that measure (continuous). **RS2** is the same idea vs sector peers. A third “leader” check in the fundamental pillar either copies RS1 (L3) or uses the wrong tool (RSI). **Lean L4:** drop L from CANSLIM-7; keep leadership in the RS pillar.

**Qualitative L (non-price)?** O’Neil did **not** mean “best company in the industry.” He warned against buying the laggard franchise that “should” catch up. True qualitative leadership (market share, category captain, new product that resets the industry) is **research**, not in Yahoo.

What Yahoo *does* have on NSE (sample of 12): **sector/industry** always; **profit and operating margins** always; **ROE** only half the time. No market share, no “#1 in industry,” no product flag.

Possible non-RS stand-ins (not classical L):

| ID | Idea | Problem |
|---|---|---|
| L6 | Top-half **operating margin vs sector peers in this scan** | Quality/franchise, not leadership; banks vs NBFCs share one Yahoo sector |
| L7 | Top-half **quarterly EPS growth vs sector peers** | Overlaps C; just C relative instead of absolute |
| L8 | Manual / research toggle | Not a screener |

Do not call margin rank “CANSLIM L.” Prefer **L4**, or a separately named quality-vs-peers rule (**L6**).

**Fold RS into L and drop the third pillar? (your proposal)**

Yes, that is coherent. RS1/RS2 **are** CANSLIM L with extra UI. A third pillar exists only to (1) score leadership on a **0–10 slider of its own**, and (2) keep **how much** a name beat Nifty/peers, not just yes/no.

**What you would lose**

- **Magnitude.** RS1 maps ±10pp vs Nifty onto 0–5. Beating Nifty by 0.2% and by 20% are different scores. A pass/fail L treats both as pass.
- **Weight.** Leadership is currently a whole pillar (`10 − fund − tech`). If L is **one of seven** fundamental ticks and fund is half the total, L is ~7% of the score. Today RS can easily be 20–40% of the total. Folding L in **shrinks** leadership unless we give it extra weight.

**Ways to do it**

| ID | Model | Clutter | Leadership weight |
|---|---|---|---|
| **L9a** | Drop RS pillar. L = pass if 63d return > Nifty. Sector vs-peers as optional second tick **L-sec** (old RS2), skip if no sector | Two pillars, two sliders | 1–2 / N fund rules |
| **L9b** | Same, but L passes only if **both** beat Nifty **and** beat sector | Even simpler | 1 / N |
| **L9c** | Drop RS pillar; L is the **old continuous 0–10 RS score mixed into the fundamental average** | Odd hybrid (binary + continuous in one pillar) | You pick a blend |
| L4 | Drop L from fund; **keep** RS pillar (rename it L in the UI) | Still three weights | Unchanged |

**Recommendation:** **L9a**, not L4, if your priority is less clutter. Two pillars: Fundamental (C, A, N, S, **L vs Nifty**, **L vs sector**, I, M) and Technical. Show the % vs Nifty and vs sector in the breakdown **as facts**, not as a third score. Accept that leadership will matter less in the total than it does today unless you later give L two ticks (which L9a already does).

Do **not** keep RSI as L. Do **not** keep RS1/RS2 toggles plus L.

**Agreed (L9a) — in `main`:** Drop the RS pillar and the RS weight slider. Two pillars only: Fundamental and Technical. L is no longer RSI. It becomes two fundamental ticks with the old RS math: **L vs Nifty** (63-day return > Nifty) and **L vs sector** (63-day return > sector peers in this scan; skip if no sector). Breakdown still shows the percentages. T1–T10 remain chart/trend confirmation; they do not compare the stock to Nifty or peers.

---

## I — Institutional sponsorship

| Field | Value |
|---|---|
| **Status** | **Locked: I1 — in `main`** |
| Sidebar / UG | Institutional ownership > 30% |
| Help | Data is often missing |
| **Code (I1)** | Yahoo `heldPercentInstitutions` > 0.30. Skip if missing. |

**What O’Neil’s I actually is**

I is **Institutional sponsorship**. He wanted **some** quality funds involved, and preferably **adding**, not a stock nobody will buy. He also warned that **too many** institutions can mean the name is already crowded. The live tell is **rising sponsor count / rising holdings**, not a one-shot percentage. We do **not** get quarter-on-quarter fund counts from Yahoo (`institutionCount` was empty on every sample name).

**What the code does**

A static cut: institutions hold more than **30% of shares outstanding**. That is a crude “is it owned by funds?” check. It is **not** quality of holders and **not** accumulation.

The help text is outdated: on this Nifty 50 sample the field was **present for 24/25** (only Tata Motors skip, Yahoo 404). It **does** split the universe, 12 pass / 12 fail.

**The India catch (why it is not straightforward)**

Yahoo’s % is of **the whole company**, not of free float. Promoter-heavy names look “under-sponsored” even when FIIs/DIIs own most of the float:

- **Fail I at 30%:** TCS 18% inst / 72% insider, Reliance 28/52, HUL 21/62, Maruti 26/62, Titan 22/59, Bajaj Finance 27/57, Adani Ent 18/75, …
- **Pass:** professionally owned banks and similar — Axis 71%, HDFC Bank 61%, ICICI 59%, Infosys 52%, L&T 53%, …

So I today is closer to “**not promoter-dominated**” than to “has institutional sponsorship.” Almost everyone has *some* institutions (all 24 are >5%).

**Options**

| ID | Rule |
|---|---|
| **I1** | Keep > 30% of outstanding; skip if missing. Simple; tilts against promoter-led names |
| I2 | Same 30%, missing = fail (punishes Yahoo holes) |
| **I3** | Drop I until we have NSE shareholding (promoter / FII / DII) |
| I4 | Pass if institutions > **10%** (has some sponsorship; almost all Nifty pass) |
| I5 | Pass if institutions > 30% **of float** (needs float + outstanding; definitions often disagree) |

**Agreed (I1) — in `main`:** Keep Yahoo institutions > 30% of outstanding; skip if missing. Relabel help so it does not say “data is often missing.” Accept promoter-led tilt: this is one dimension of a strength score, not a go/no-go veto; users can disable I or raise technical weight.

---

## M — Market direction

| Field | Value |
|---|---|
| **Status** | **Locked: M1 — keep on every stock. In `main`** |
| Sidebar / UG | Nifty 50 above its 200-DMA |
| **Code (M1)** | `^NSEI` last close > SMA200. Skip if < 200 bars. **Same pass/fail for every stock in a scan.** |

**What O’Neil’s M actually is**

M is **Market direction**: most stocks follow the general market, so he did not want you buying (or staying full) in a confirmed downtrend. Classic checks include the index vs 50/200-DMA and distribution days. It is a **tape / timing** rule, not a company attribute.

**What the code does**

One Nifty test, copied onto every row. If Nifty is above the 200-DMA, **every** name gets M. If not, **every** name fails M. It does **not** rank Reliance vs TCS.

On 28 Aug 2026, Nifty was about **2% below** its 200-DMA (and the 200-DMA was not rising). So in a scan today **M fails for the entire universe**.

**Why that matters for a strength screener**

Failing M lowers everyone’s fundamental score by the same fraction (one fewer pass in the same denominator). **Rank order among stocks does not change.** What changes is the **absolute** number (e.g. 6.8 vs 7.7), which matters if you use a cutoff or compare scores across different market days.

**Options**

| ID | Rule |
|---|---|
| **M1** | Keep Nifty > 200-DMA on every stock. Absolute scores move with the tape; ranking does not |
| M2 | Also require the 200-DMA sloping up over 5 bars (stricter; still the same for every name) |
| **M3** | Do not put M in the per-stock score. Show “Nifty vs 200-DMA” once as a banner / digest header |

**Agreed (M1) — keep in the per-stock score.** Same field for everyone: Nifty > 200-DMA. Dock all or dock none. Preserves the CANSLIM letter. Help text will explain that M does not rank stocks against each other.

**Also agreed for the batch:** rewrite User Guide + sidebar help so each locked C/A/N/S/L/I/M and T1–T10 states the actual rule in plain language (not the old RSI-L / annual-revenue wording).

---

## T1–T10 — Technical

| Field | Value |
|---|---|
| **Status** | **Locked: G1-keep, T2-keep, G3-keep, G4-keep** — all T1–T10 left as coded (no remaining T patches) |
| Scoring | Pass/fail. Missing data **fails** (unlike C/A/N…). Need ≥ 30 daily bars or the whole pillar is 0. |

These are **chart health** checks on the stock itself, not vs Nifty (that is L). They overlap each other on purpose (trend + oscillators on three timeframes).

| ID | What it asks | Exact test | Nifty sample pass (24 names) |
|---|---|---|---:|
| T1 | Uptrend and coiled on the 50-DMA | Close > SMA200 **and** within 5% of SMA50 | 9/24 |
| T2 | Tight coil near 20- or 50-DMA | Within 5% of SMA50 **or** SMA20, **and** 10-day vol ≤ 6% | **23/24** |
| T3 | Stage 2, not extended | SMA200 < close ≤ 1.25 × SMA200 | 10/24 |
| T4 | MAs still rising | SMA50 and SMA200 each higher than 5 bars ago | 6/24 |
| T5 | Monthly momentum | Monthly RSI > 50 and higher than 2 months ago | 9/24 |
| T6 | Weekly momentum | Same on weekly | 4/24 |
| T7 | Daily momentum | Daily RSI > 50 and higher than 2 days ago | 6/24 |
| T8 | Monthly MACD | Monthly MACD line higher than 2 months ago | 13/24 |
| T9 | Weekly MACD constructive | Weekly MACD > signal, MACD > 0, line rising | 7/24 |
| T10 | Daily MACD | Daily MACD line higher than 2 days ago | 7/24 |

Median technical score on that sample: **3.5 / 10**. ICICI 9, Titan/Adani Ent 8; many large caps 1 (often **T2 only**).

**Notes**

- **T2 is almost a free point** on Nifty 50 (same inert 6% vol we saw on old S). It still fails Kotak in this sample.
- “Rising” / “sloping up” is **two points**, not a regression: now vs 5 bars (T4) or 2 bars (RSI/MACD).
- T7 is the old L (RSI), which is fine now that L is vs Nifty/sector.
- T1 and T3 both need close > 200-DMA; T3 also caps extension.
- Unlike fundamentals, a NaN SMA/RSI **fails** the tick rather than skipping it.

**Group 1 (T1, T3, T4) — locked: G1-keep.** Leave the three Stage 2 tests as written. They already split coiled (T1), not-extended (T3), and MAs still ticking up (T4).

**Group 2 (T2) — locked: T2-keep.** Leave tightness as a calm-tape tick (near 20- or 50-DMA, 10-day vol ≤ 6%). Trend is already T1/T3/T4.

**Group 3 (T5–T7) — locked: G3-keep.** RSI > 50 and rising on monthly, weekly, and daily.

**Group 4 (T8–T10) — locked: G4-keep.** Leave the MACD stack as written: monthly and daily only “sloping up” (line higher than 2 bars ago; can still be below zero or below signal); weekly is the strict constructive test (line > signal, line > 0, and rising).

Rationale (user): weekly strength is an **early** tell that monthly is likely to follow, so monthly only needs to be sloping up. Daily sloping up **on the back of** that weekly intermediate-term strength is a **swing-entry** tell — the daily timeframe ready after a retracement. That is why T9 is tighter than T8/T10; the three ticks are not meant to be the same test on three calendars.

---

## RS1 / RS2 — folded into L (L9a)

No longer a third pillar. 63-day vs Nifty and vs sector become **L vs Nifty** and **L vs sector**. Continuous 0–5 mapping is dropped; breakdown still shows the %.

---

## Locked decisions

Implemented in scoring + User Guide. T1–T10 reviewed in groups:

- **C2** — quarterly EPS YoY.
- **A2** — quarterly Total Revenue YoY; skip if missing.
- **N2 + N4** — within 10% of 52-week high; high from daily bars (merge Yahoo if present).
- **S3 (20 trading days)** — up-volume > down-volume; skip if missing.
- **L9a** — two-pillar model; **L** vs Nifty and **Ls** vs sector; RS pillar removed.
- **I1** — Yahoo institutions > 30%; skip if missing.
- **M1** — Nifty > 200-DMA on every stock.
- **Help/User Guide** — rewritten to match the rules above. T1–T10 described as currently coded.

- **T Group 1 (T1/T3/T4)** — **G1-keep** (not a code change).
- **T Group 2 (T2)** — **T2-keep** (not a code change).
- **T Group 3 (T5–T7)** — **G3-keep** (not a code change).
- **T Group 4 (T8–T10)** — **G4-keep** (not a code change). Weekly = early intermediate-term MACD strength; monthly = slope only; daily = slope as swing-entry after retracement.

## Pending

None on T1–T10. Scoring parameter audit for C/A/N/S/L/I/M and T is complete; remaining work is outside this log (e.g. optional later tech missing-data=skip).
