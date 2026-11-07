# Test fixtures

## `split_mini/` — synthetic split (one business)

Mirrors the competition layout (`rulebook.md`, `calendar.csv`, `questions.jsonl`, `answers.jsonl`, `data/<business_id>/`). The data is invented; the rulebook is a short original text in the style of the real one. It is **not** derived from the training split.

`data/biz_fx01/ban_hang.csv` — 12 orders (DH001–DH012), one row per order line, UTF-8 with BOM, ISO dates, plain integers. Notable rows: DH004 cancelled (Huỷ), DH006 returned (Trả hàng), DH008 in delivery (Đang giao, counts) with a 999-đồng line discount, DH012 dated **after** `as_of_date` (2026-03-06 > 2026-03-04). Data range 2026-01-20 … 2026-03-06.

### Expected answers (computed by hand; all questions use `as_of_date = 2026-03-04`, a Wednesday)

Valid orders exclude Huỷ and Trả hàng.

| id | Question (short) | Window | Derivation | Answer |
|---|---|---|---|---|
| fx_q01 | revenue last week | 02-23 … 03-01 (Mon–Sun) | DH007 61,000 + DH008 69,001 | 130001 |
| fx_q02 | average order value last week | same | (61,000 + 69,001) / 2 = 65,000.5 → money, half up | 65001 |
| fx_q03 | cancel rate Feb 2026 | 02-01 … 02-28 | 1 cancelled (DH004) of 6 orders DH003–DH008, all statuses | 16.67 |
| fx_q04 | top 3 best sellers this month | 03-01 … 03-04 | qty: SP01 2+1=3, SP04 1+2=3, SP03 1+1=2, SP02 0 (DH012 is after today); tie SP01/SP04 → code ascending | Cà phê sữa (M), Bánh mì que, Bạc xỉu (M) |
| fx_q05 | revenue Jan and Feb 2026, in that order | Jan (partial coverage 12/31), Feb | Jan 58,000 + 35,000; Feb 117,000 + 94,000 + 61,000 + 69,001 | [93000, 341001] |
| fx_q06 | day with highest revenue in Feb 2026 | Feb | 02-03 117,000 > 02-14 94,000 > 02-27 69,001 > 02-24 61,000 | 2026-02-03 |
| fx_q07 | revenue Dec 2025 | 2025-12 | entirely before the data range | unanswerable |
| fx_q08 | cups of Trà đào (M) this week | 03-02 … 03-04 | no valid sale in the window (DH012 is after today) — a real zero | 0 |
| fx_q09 | gross profit Feb 2026 | Feb | no cost column anywhere | unanswerable |
| fx_q10 | Feb revenue higher than Jan? | Feb vs Jan | 341,001 > 93,000 | true |
| fx_q11 | customer with most revenue Feb 2026 | Feb | Anh Tú 117,000 + 94,000 + 69,001 = 280,001; Chị Lan 61,000; Khách lẻ excluded | Anh Tú |
| fx_q12 | number of orders, last 7 days | 02-26 … 03-04 | DH008, DH009, DH010, DH011 | 4 |
| fx_q13 | revenue table by customer Feb 2026 | Feb | as fx_q11 | Anh Tú 280001; Chị Lan 61000 |

## `scripted/split_mini.jsonl` — development-only model responses

What a model *would* return for the parse and solve stages of each fixture question (fx_q06 deliberately starts with a wrong column so the repair path runs). Used only with `--dev` and `model.backend = "scripted"`. Editing it changes plumbing tests, not accuracy.
