# FYERS vs Groww — Market Data Capabilities Comparison

**Status:** Research complete, read-only. No code, database, or config changes were made in this research.
**Date:** 2026-08-15

---

## 1. Evidence Classification Key

Every claim below is tagged with where it came from:

- **[DOCUMENTATION]** — stated in FYERS's own API reference PDF (`API - FYERS.pdf`, a 168-page full export of `myapi.fyers.in/docsv3`, supplied directly by the user and read cover-to-cover, sequentially, pages 1–168, no gaps).
- **[OUR CODE]** — read directly from this repo's `.py` files in this session (grep + targeted reads, this pass).
- **[DATABASE]** — read directly from this Postgres instance.
- **[INFERENCE]** — a conclusion drawn from the above, not a direct quote/observation.
- **[RECALLED, UNVERIFIED THIS PASS]** — something established about Groww's *official documentation* earlier in this same conversation, before context was compacted. I no longer have the exact source URL or verbatim text in front of me. Treat these as lower-confidence than everything else in this report and re-verify before relying on them.
- **[GAP]** — a question the original brief asked that neither source answered in this pass.

No blog posts, Reddit threads, or YouTube videos were used as evidence anywhere in this report.

---

## 2. Methodology Note (why this report looks the way it does)

The original ask was a full FYERS vs Groww market-data comparison, grounded in primary sources only. Early attempts to reach `myapi.fyers.in` directly (WebFetch, browser navigation) were blocked by both the site's own Cloudflare bot-protection and a harness-level policy restriction — confirmed independently, not assumed. Rather than route around either, I asked you for an alternative, and you supplied a full 354-page print export of the live docs site as a PDF. I read all 168 pages that contained content (some trailing pages were blank/boilerplate), strictly sequentially per your explicit instruction, after an earlier attempt to skip ahead was corrected.

**Consequence:** the FYERS side of this report is deep and exhaustively primary-sourced. The Groww side is not backed by an equivalent from-scratch documentation read in *this* pass — that research happened earlier in the same conversation and its exact citations were lost to context compaction. Rather than restate those recollections as if freshly verified, I re-grounded the Groww side in something arguably stronger for your purposes: **this codebase's actual production usage of the official `growwapi` SDK**, including code comments that record empirically-discovered API limits. Where I'm relying on the older, unverified recollection, it's marked as such and kept separate from what I just confirmed.

---

## 3. Documentation Coverage Confirmation

You asked, pointedly, whether I'd actually gone through the FYERS docs. Here's the honest accounting: the PDF's 168 content pages covered every section on your pasted URL list — Introduction, Libraries & SDKs, Request/Response Structure, App Creation, Authentication & Login Flow, Sample Code, User/Transaction Info/Reports, Order Placement (sync/async/multi/multileg), GTT, Smart Orders, Modify/Cancel Orders, Manage Positions, Margin Calculator, Broker Config (Market Status, Symbol Master), EDIS, Price Alerts, WebSocket (General/Order/Data — all sub-modes), Order WebSocket Usage Guide, Tick-by-Tick WebSocket, Appendix (Fytoken, exchange/segment codes, instrument types, symbology, product/order/position/holding types), and the full Change Log back to the API v2 launch.

**Not covered by the PDF, because it wasn't part of the export:** the standalone Terms & Conditions and Privacy Policy pages (only linked from every page's footer, never opened as content), and any pricing/plan page distinct from the rate-limit tables inside the API reference itself. These are flagged as [GAP] in §14.

---

## 4. Historical Data — Interval / Resolution Matrix

### FYERS [DOCUMENTATION]

Single endpoint: `GET https://api-t1.fyers.in/data/history`

| Resolution value | Meaning |
|---|---|
| `"D"` / `"1D"` | Daily |
| `"5S"`, `"10S"`, `"15S"`, `"30S"`, `"45S"` | Seconds (added 13 Mar 2024 per changelog) |
| `"1"`, `"2"`, `"3"`, `"5"`, `"10"`, `"15"`, `"20"`, `"30"`, `"45"`, `"60"`, `"120"`, `"180"`, `"240"` | Minutes |
| `"1W"` | Weekly (added 27 Mar 2026 — **recent**, per changelog) |
| `"1M"` | Monthly (same changelog entry) |

Request params: `symbol`, `resolution`, `date_format` (0=epoch, 1=yyyy-mm-dd), `range_from`, `range_to`, `cont_flag` (continuous F&O contract stitching), **`oi_flag`** ("set flag to '1' enable oi as a part of candle").
Response candle shape: `[epoch, open, high, low, close, volume]` — an array, not an object, per candle.

### Groww [OUR CODE]

Single SDK method: `growwapi.GrowwAPI.get_historical_candle_data(trading_symbol, exchange, segment, start_time, end_time, interval_in_minutes)` — confirmed used identically across [fetch_full_history.py](fetch_full_history.py), [price_fetcher.py](price_fetcher.py), and [bot.py](bot.py).

Groww's interval is a raw integer count of minutes, not a named resolution string. Values actually exercised in this codebase:
- `5` (5-minute)
- `15` (unused directly, but budgeted for — see limits table)
- `60` (1-hour)
- `1440` (daily)
- `10080` (weekly — `7 × 1440`, used specifically as a workaround, see §5)

Response shape: `{"candles": [[timestamp, open, high, low, close, volume], ...]}` — the same six-field array shape as FYERS, which simplified this codebase's ingestion code (`_insert_candles` in `fetch_full_history.py` doesn't need per-provider branching for the candle tuple itself).

No seconds-resolution, no native weekly/monthly resolution parameter (weekly is synthesized by requesting `interval_in_minutes=10080`, which is a *sampling* trick, not a first-class weekly-candle mode with its own semantics — worth being aware this may aggregate differently than FYERS's dedicated `"1W"`).

**[GAP]** Whether Groww has a true seconds-level history endpoint at all — nothing in this codebase requests it, and I have no primary-source Groww documentation open in this pass to confirm or deny it.

---

## 5. Historical Data — Retention Boundaries

### FYERS [DOCUMENTATION] — quoted verbatim from the PDF

> "Unlimited number of stocks history data can be downloaded in a day."
> "Up to 100 days of data per request for resolutions of 1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 120, 180, and 240 minutes. **Data is available from July 3, 2017.**"
> "For 1D, 1W and 1M resolutions up to 366 days of data per request..."
> "For Seconds Charts the history will be available only for 30-Trading Days."

This is unambiguous, dated, and in writing. Minute-level equity data goes back to **2017-07-03**, chunked 100 days per request; daily/weekly/monthly goes back further, chunked 366 days per request; seconds data is a rolling 30-trading-day window only.

### Groww [OUR CODE] — empirically discovered, not documented

Two separate scripts in this repo record two *slightly different* self-discovered boundaries for the same `interval_in_minutes=1440` (daily) request:

- [fetch_full_history.py:31](fetch_full_history.py:31) — comment: `"daily": {"minutes": 1440, "max_days": 700, "chunk_days": 365}` → **~1.9 years** per request.
- [price_fetcher.py:57](price_fetcher.py:57) — comment: `"Fetch weekly candles for 5+ years (1440-min only supports ~3 years)"` → implies daily tops out around **~3 years**.

These two numbers don't agree with each other. Neither is sourced from a Groww doc quote — both are prior engineering notes, presumably arrived at by trial and error against the live API. Take this as evidence that **Groww's own retention boundary for daily candles was not clearly documented enough for this codebase's own authors to state it consistently**, which is itself a meaningful data point in a documentation-quality comparison, distinct from whatever the actual true boundary is.

The workaround both scripts converge on is real: when the daily interval hits its (fuzzy) ceiling, [price_fetcher.py](price_fetcher.py) switches to `interval_in_minutes=10080` (weekly) specifically because that interval "supports full history" — i.e., whatever the true daily-candle cutoff is, weekly candles apparently don't hit it, at least not within the 5-year window this code targets.

[fetch_full_history.py:171](fetch_full_history.py:171) starts its full backfill at `datetime(2020, 1, 1)` — consistent with the earlier-session recollection below, though I can't rule out this date being an arbitrary choice by whoever wrote the script rather than a discovered API floor.

**[RECALLED, UNVERIFIED THIS PASS]** Earlier in this conversation (before compaction), research into Groww's own documentation reportedly found conflicting retention claims: **3 months** of history via a deprecated method, versus an ambiguous **"since 2020"** claim via a newer method. This is *consistent* with what the code shows (2020 start date, fuzzy multi-year daily ceiling) but I do not have the original doc citation in front of me to confirm it's accurate. Re-verify against Groww's current docs before treating this as settled.

**Bottom line on retention:** FYERS states its boundary in writing, with a specific date (2017-07-03) and specific per-resolution day-counts. Groww's boundary, at least as encountered by this codebase's own authors, had to be discovered by trial and error and the two discoveries don't fully agree with each other.

---

## 6. Live Market Data — REST

### FYERS [DOCUMENTATION]

- **Quotes:** `GET https://api-t1.fyers.in/data/quotes?symbols=...` — max **50 symbols** per call. Fields: `ch`, `chp`, `lp`, `spread`, `ask`, `bid`, `open_price`, `high_price`, `low_price`, `prev_close_price`, `atp`, `volume`, `short_name`, `exchange`, `description`, `original_name`, `symbol`, `fyToken`, `tt`. No last-traded-qty/time in this endpoint.
- **Market Depth:** `GET https://api-t1.fyers.in/data/depth?symbol=...&ohlcv_flag=1` — **max 1 symbol per request**, 5-level bid/ask (price/volume/orders each). Includes `ltq`, `ltt`, `ltp`, `oi`, `oiflag`, `pdoi`, `oipercent`, `lower_ckt`, `upper_ckt`, `expiry`.

### Groww [OUR CODE]

- **LTP:** `groww.get_ltp(segment=DEFAULT_SEGMENT, exchange_trading_symbols=f"{DEFAULT_EXCHANGE}_{symbol}")` — [bot.py:317](bot.py:317). Signature suggests multi-symbol batching via a combined string, though this codebase only ever calls it one symbol at a time.
- **Quote:** `groww.get_quote(exchange=DEFAULT_EXCHANGE, segment=DEFAULT_SEGMENT, trading_symbol=symbol)` — [bot.py:328](bot.py:328), single-symbol.

**[GAP]** Exact field list Groww's `get_quote`/`get_ltp` return, per-call symbol batch limits, and whether Groww has a dedicated 5-level (or deeper) market-depth REST endpoint comparable to FYERS's `/data/depth`. Nothing in this codebase calls a depth-specific Groww method — [OUR CODE] evidence here is silent, not negative.

---

## 7. Live Market Data — WebSocket

### FYERS [DOCUMENTATION] — extensively documented, four distinct modes on the Data Socket

All connect via the `FyersDataSocket` client (`fyers_apiv3.FyersWebsocket.data_ws`), one instance per app (single-instance enforced), auto-reconnect up to 50 retries, subscription cap of **5,000 symbols per connection** (raised from 200 on 26 Mar 2024), configurable queue-processing interval (1ms–2000ms).

| Mode | `type` code | Fields |
|---|---|---|
| `SymbolUpdate` | `sf` | Full quote: `ltp`, `prev_close_price`, `high/low/open_price`, `ch`, `chp`, `vol_traded_today`, `last_traded_time`, `bid_size`, `ask_size`, `bid_price`, `ask_price`, `last_traded_qty`, `tot_buy_qty`, `tot_sell_qty`, `avg_trade_price` |
| Index update | `if` | Same shape, index-scoped |
| `DepthUpdate` | `dp` | `bid_price1–5`, `ask_price1–5`, `bid_size1–5`, `ask_size1–5`, `bid_order1–5`, `ask_order1–5` (order counts) — 5-level, matches the REST depth endpoint |
| Lite mode | `sf` | `{symbol, ltp, type}` only — minimal payload for LTP-only consumers |

Separately, the **General/Order Socket** (`wss://socket.fyers.in/trade/v3`) pushes order/trade/position/EDIS/price-alert updates over its own connection, subscribed via a `SUB_ORD` JSON message with an `action_data` list (`orders`, `trades`, `positions`, `edis`, `pricealerts`, `login`).

### Groww [OUR CODE]

**No WebSocket usage found anywhere in this codebase.** `grep` for `websocket`, `WebSocket`, and `subscribe` against [bot.py](bot.py) and every other file importing `growwapi` returned zero hits. Live data in this system is obtained exclusively via the REST `get_ltp`/`get_quote` calls in §6, called on a scheduler loop (per project context, as frequently as every 6 seconds for some tasks).

**This is a genuine architectural asymmetry worth being direct about:** it is not evidence that Groww lacks a streaming product — the official `growwapi` package may well ship one — only that this codebase has never used it. Comparing "FYERS has a documented 4-mode WebSocket" against "Groww: unknown" is not apples-to-apples; it's "FYERS: verified via docs" vs. "Groww: unverified in this pass, [GAP]."

---

## 8. Tick-by-Tick (TBT) / Order-Flow Data

### FYERS [DOCUMENTATION] — the single most detailed section in the whole PDF

- **Scope:** "Tick-by-tick data is exclusively available only for NFO (NSE Futures & Options) and NSE (Equity) instruments" — equity support was added later, **23 Jun 2025** per the changelog; originally F&O-only.
- **Transport:** `wss://rtsocket-api.fyers.in/versova`. Requests are JSON; **responses are Protocol Buffers**, not JSON — a real integration cost, not a triviality. Schema published at `https://public.fyers.in/tbtproto/1.0.0/msg.proto`, with pre-compiled bindings for Python/Node/Go.
- **Update model:** first packet on subscribe is a full **snapshot**; every subsequent packet is an incremental **diff** the client must apply itself (official SDKs do this automatically; a custom protobuf integration would not get this for free).
- **Depth:** up to **50 levels** (`TBT 50 Market Depth`, `MarketLevel.num` ranges 0–49), versus 5 levels on the regular REST/WebSocket depth.
- **Channels:** subscriptions are grouped into up to 50 numbered channels per connection, independently pausable/resumable — lets a client stop/start whole groups of symbols without re-subscribing.
- **Rate limits (exact):** 3 active connections per app per user; **only 5 symbols per connection** in market-depth mode; 50 channels per connection.

The protobuf `MarketFeed` message actually carries five possible payload kinds (`quote`, `eq`/ExtendedQuote, `dq`/DailyQuote, `ohlcv`, `depth`) — the human-readable docs narrate depth mode specifically, but the wire schema is broader than that framing suggests.

### Groww [RECALLED, UNVERIFIED THIS PASS] / [GAP]

No tick-by-tick or protobuf-based feed was located in this codebase's Groww usage, and I have no verified primary-source confirmation either way from this pass. This is a clean [GAP] — flag it as the single biggest open question if TBT data matters to your use case, and verify directly against Groww's current API docs before concluding they don't have an equivalent.

---

## 9. Options Chain & Greeks

### FYERS [DOCUMENTATION]

`GET https://api-t1.fyers.in/data/options-chain-v3?symbol=...&strikecount=...&greeks=1` — max `strikecount=50`. With `greeks=1`, the response includes real delta/gamma/theta/vega/iv values per strike, plus `callOi`/`putOi`, `expiryData[]` (date/expiry/expiry_flag W|M), `indiavixData`, and per-strike `ask/bid/fyToken/ltp/ltpch/ltpchp/oi/oich/oichp/option_type/prev_oi/strike_price/symbol/volume`, and the underlying future's price (`fp`/`fpch`/`fpchp`).

**Correction to an earlier claim in this same research effort:** an earlier pass (based on community forum posts, not documentation) had concluded Greeks were *not* returned by FYERS's API. That was wrong — the primary-source docs show a full worked example with real Greek values under the `greeks=1` flag. This report supersedes that earlier claim.

### Groww [OUR CODE] — confirmed with real evidence, not inference

[fno_trader.py:398](fno_trader.py:398): `groww.get_option_chain(instrument_key, expiry_date=expiry_date, ...)`. [fno_trader.py:480–491](fno_trader.py:480) shows this codebase reading `opt["greeks"].get("delta", 0)` directly out of the response — **Groww's official SDK also returns Greeks per strike, and this codebase actively consumes them** (used to compute affordable-option filters). [fno_trader.py:366](fno_trader.py:366)'s `get_expiries(instrument_key)` mirrors FYERS's `expiryData[]`.

**Net:** on Greeks availability specifically, FYERS and Groww are at parity, both confirmed by direct evidence (FYERS via documentation, Groww via this codebase's actual production use of the response).

---

## 10. OI-in-History-Candles (correction)

**Correction to an earlier claim:** an earlier pass reported this as "CONTRADICTED" — two conflicting community-forum answers on whether FYERS's historical candles include open interest. The primary-source docs resolve this cleanly: the `history` endpoint takes an **`oi_flag`** request parameter — "set flag to '1' enable oi as a part of candle" — documented with no ambiguity. **Yes, OI is available in FYERS history candles, opt-in via `oi_flag=1`.** This report supersedes the earlier "contradicted" framing.

**[GAP]** Whether Groww's `get_historical_candle_data` has an equivalent OI-in-candle option — not exercised anywhere in this codebase's historical-fetch code, and not verified against current Groww docs in this pass.

---

## 11. Instrument / Symbol Master

### FYERS [DOCUMENTATION]

CSV and JSON downloads per exchange-segment at `public.fyers.in/sym_details/...` (`NSE_CD`, `NSE_FO`, `NSE_COM`, `NSE_CM`, `BSE_CM`, `BSE_FO`, `MCX_COM`). JSON schema is rich: `fyToken`, `isin`, `exSymbol`, `symDetails`, `symTicker`, `exchange`, `segment`, `exSymName`, `exToken`, `exSeries`, `optType`, `underSym`, `underFyTok`, `exInstType`, `minLotSize`, `tickSize`, `tradingSession`, `lastUpdate`, `expiryDate`, `strikePrice`, `qtyFreeze`, **`tradeStatus`** (1=Active/0=Inactive — the closest thing to a delisted flag), `currencyCode`, `upperPrice`, `lowerPrice`, `faceValue`, `qtyMultiplier`, `previousClose`, `previousOi`, `asmGsmVal`, `exchangeName`, `symbolDesc`, `is_mtf_tradable`, `mtf_margin`, `stream`, `isCasEligible`.

### Groww [OUR CODE]

Groww's `trading_symbol` is used as a plain string key throughout this codebase (e.g. `"NIFTY"`, `"HDFCBANK"`) alongside separately-maintained local config for lot sizes, tick size, and weekly-expiry weekday — see [fno_trader.py:59-65](fno_trader.py:59). This strongly suggests **this codebase does not consume a Groww-provided instrument master programmatically**; contract specs (lot size, tick size, expiry weekday) are hardcoded locally rather than pulled from a Groww symbol-master feed. That's either because Groww doesn't expose an equivalent machine-readable master (unverified), or because this codebase simply chose to hardcode a small, static universe instead of consuming one. **[GAP]** — can't distinguish those two explanations from code alone.

---

## 12. Rate Limits

### FYERS [DOCUMENTATION] — exact, and internally corroborated

| Tier | Per-second | Per-minute | Per-day |
|---|---|---|---|
| Standard | 10 | 200 | 100,000 |
| Prime | 10 | 600 | 200,000 |

Exceeding the per-minute limit more than 3 times in a day blocks the account for the rest of that day. The 100,000/day figure is corroborated independently by the Change Log: "**22 Aug 2024** — Increased API rate limit from 10,000 requests per day to 1 Lakh requests per day (10x increase)" — two different parts of the same document agree, which is as close to internal cross-verification as a single-source document can offer.

TBT WebSocket has its own separate limits (§8): 3 connections/app/user, 5 symbols/connection, 50 channels/connection.

### Groww [OUR CODE] — not a documented limit, a self-imposed throttle

[fetch_full_history.py:148](fetch_full_history.py:148): `time.sleep(0.25)` between chunked historical requests, labeled `# Rate limit` in a comment. This is **this codebase's own defensive throttle**, not a quoted Groww rate-limit number — treat it as evidence someone hit a limit and backed off empirically, not as Groww's documented ceiling. **[GAP]** — Groww's actual published per-second/minute/day limits were not re-verified in this pass.

---

## 13. Authentication

### FYERS [DOCUMENTATION]

`GET https://api-t1.fyers.in/api/v3/generate-authcode` → `POST .../validate-authcode` (requires `appIdHash` = SHA-256 of `api_id:app_secret`) → returns `access_token` + `refresh_token`. Refresh token valid 15 days. Permission Templates at app-creation are independently grantable scopes — Basic / Transactions Info / Order Placement / **Market Data** (Historical, Depth, Quotes) — confirming a read-only, trading-disabled, market-data-only app is a first-class supported configuration.

**Note on a specific claim I can't fully stand behind:** an earlier read of this same PDF surfaced a note that refresh-token behavior "will be discontinued from 1st April" without a clearly captured year. I don't have that exact page in front of me now to re-confirm the year with confidence — don't rely on this detail without re-checking the Authentication section of the PDF directly.

### Groww [OUR CODE]

Single long-lived `GROWW_ACCESS_TOKEN` environment variable, read directly by every module that needs a client (`_get_groww()` pattern repeated near-identically in [bot.py](bot.py), [fetch_full_history.py:44](fetch_full_history.py:44), [price_fetcher.py:20](price_fetcher.py:20), and others). [token_refresher.py](token_refresher.py) exists as a separate module, implying some refresh automation, not inspected in depth this pass. No scoped/permission-template concept was found — the token appears to be all-or-nothing for whatever the underlying Groww app was provisioned with.

---

## 14. Legal / Data-Usage Terms

**[GAP] — not covered by the source material available in this pass.** The PDF is purely an API reference export; "Terms & Conditions" and "Privacy Policy" appear only as footer links on every page, never as expanded content. No FYERS data-redistribution, redistribution-license, or commercial-use restrictions were reviewed. If licensing terms for downstream use of FYERS market data matter to your decision, that requires a separate, dedicated read of `fyers.in`'s legal pages — out of scope of what was available here.

---

## 15. Code-Coupling Analysis (how deep is Groww baked into this codebase)

[OUR CODE], via `grep -l "growwapi"` across the repo:

**12 files directly import `growwapi`:** [bot.py](bot.py), [app.py](app.py), [get_token.py](get_token.py), [fetch_full_history.py](fetch_full_history.py), [fundamental_analysis.py](fundamental_analysis.py), [fii_tracker.py](fii_tracker.py), [fno_trader.py](fno_trader.py), [paper_trader.py](paper_trader.py), [price_fetcher.py](price_fetcher.py), [portfolio_analyzer.py](portfolio_analyzer.py), [token_refresher.py](token_refresher.py), [trailing_stop.py](trailing_stop.py).

The `_get_groww()` client-construction pattern is duplicated (not centralized) across at least three of these files, each independently reading `GROWW_ACCESS_TOKEN` from the environment. `SEGMENT_CASH` and similar constants are pulled directly off the `GrowwAPI` class rather than through a wrapper. **This is a meaningful migration-cost signal, independent of the data-capability comparison above:** switching brokers isn't just "swap the data source" — it's touching order placement, position sync, trailing stops, fundamental data, FII tracking, and portfolio analysis, all of which currently call the Groww SDK directly rather than through an abstraction layer.

---

## 16. Side-by-Side Summary

| Capability | FYERS | Groww |
|---|---|---|
| Historical resolutions | Seconds, 1–240 min, D, W, M — all documented | Raw minute integers; weekly is a sampling trick, not native |
| Minute-data retention | 2017-07-03 onward, stated in writing, 100 days/request | Fuzzy multi-year ceiling, discovered empirically, two internal comments disagree |
| Seconds data | Documented, 30-trading-day rolling window | [GAP] — not found |
| OI in history candles | Yes, via `oi_flag=1`, documented | [GAP] — not exercised in this codebase |
| Quotes (REST) | Up to 50 symbols/call, documented fields | Used, single-symbol per call in this codebase, field list not confirmed |
| Market depth (REST) | 5-level, 1 symbol/call, documented | [GAP] — no depth call found in this codebase |
| WebSocket (LTP/quote/depth) | 4 documented modes, 5000-symbol cap | [GAP] — not used anywhere in this codebase |
| Tick-by-tick / order flow | Documented: protobuf, 50-depth, NFO+NSE-EQ, strict rate limits | [GAP] — not found |
| Options chain + Greeks | Documented, `greeks=1` | **Confirmed via this codebase's actual production use** |
| Instrument master | Documented CSV/JSON, rich fields | [GAP] — this codebase hardcodes contract specs instead |
| Rate limits | Exact, cross-corroborated within the doc | Only a self-imposed throttle observed, not an official number |
| Auth model | Scoped permission templates, refresh token | Single long-lived token, all-or-nothing |
| Codebase coupling | N/A (not currently used) | Deep — 12 files, no abstraction layer |

---

## 17. Confidence Audit

**High confidence (primary source, this pass):** everything in §4–5 and §7–9's FYERS columns, §12's rate-limit table, §13's FYERS auth flow, all of §11's FYERS symbol-master fields.

**High confidence (direct code read, this pass):** everything in the Groww columns of §6, §9, §13, and all of §15.

**Lower confidence, flagged individually:** the refresh-token discontinuation date in §13; the Groww "3 months / since 2020" retention claim in §5 (consistent with but not proven by the code evidence found this pass).

**Explicit gaps, not guessed at:** Groww WebSocket/streaming existence (§7), Groww tick-by-tick (§8), Groww instrument master (§11), Groww's actual documented rate limits (§12), and all of FYERS's legal/licensing terms (§14).

---

## 18. Recommendation

For anything requiring **documented, dated, written guarantees** about historical-data depth, resolution granularity, or rate limits — FYERS's documentation is materially more complete and internally consistent than what this codebase's own engineering history shows for Groww. The clearest single data point: FYERS states its minute-data floor as a specific calendar date in writing; this codebase's own authors had to discover Groww's equivalent floor by trial and error, and left two different, disagreeing estimates in code comments.

Where FYERS and Groww are shown to be at genuine parity by real evidence rather than assumption: options-chain Greeks (§9) — both return them, confirmed on both sides.

The single largest unresolved question is Groww's WebSocket/tick-by-tick capability (§7–8) — not because evidence points to Groww lacking it, but because this pass found no evidence either way. **Before this comparison can support a "switch to FYERS" or "stay on Groww" decision on live/tick data specifically, Groww's current official documentation needs the same page-by-page primary-source treatment this report gave FYERS.** Everything else here is on solid enough footing to act on.

Separately, and worth weighing regardless of which provider wins on data capability: §15's coupling analysis means adopting FYERS market data without also migrating order placement would leave this codebase running two brokers' SDKs side by side — a real integration cost that a pure data-capability comparison doesn't capture.
