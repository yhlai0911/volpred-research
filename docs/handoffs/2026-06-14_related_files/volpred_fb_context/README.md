# VolPred Facebook Posting Library

This folder is the operating library for posting VolPred articles to Ivan Lai's personal Facebook.

## Hard Rules

- Read the full VolPred article before scoring, ranking, drafting, or publishing.
- Do not put any VolPred URL in the Facebook post body.
- Put the full article URL in the first comment only, using the canonical form `全文：https://volpred.zeabur.app/v3/reports/{id}`.
- Draft post bodies and replies with the `anti-ai-style` standard: natural Taiwan Mandarin, no generic AI tone, no fake insight posture, no bloated structure.
- Do not judge duplicate status from local notes alone. Check in this order:
  1. `posted-links.json` and local dashboard/profile notes.
  2. Ivan Lai's live Facebook profile/content library when needed.
  3. Facebook-visible or web-visible VolPred/platform posts, because VolPred may publish the same article to Facebook independently.
- Cache every check result in `posted-links.json` or the candidate's `checks` field so future runs can avoid rechecking from zero.
- Before any future automation publishes, it must verify: Ivan Lai account, target candidate, no duplicate block, article still reachable, post body has no URL, first comment URL exists.

## Scoring

Total score is out of 100 before penalties.

| Dimension | Weight | Meaning |
|---|---:|---|
| Time sensitivity | 25 | Event is current, expiring soon, or tied to a market date. |
| Audience pull | 20 | A normal FB reader would stop scrolling because it touches TSMC, CPI, Fed, age/retirement, or a popular market argument. |
| Practical value | 20 | Reader can change a concrete judgment, question, or checklist after reading. |
| Readability | 15 | The article can be explained without losing people in model jargon. |
| Evidence strength | 10 | Numbers, sample period, event study, or tables are clear enough to defend. |
| Novelty vs recent FB | 10 | Not too close to Ivan's recently posted VolPred topics. |

Penalties and blocks:

- Exact URL already posted by Ivan: block.
- Same VolPred article already posted by VolPred/platform Facebook and likely redundant for Ivan today: hold for manual review.
- Recent near-duplicate topic on Ivan FB: minus 15 to 30.
- Article full text unread: block.
- Event has expired or the market date has passed: minus 25 or hold for rewrite.
- Candidate link cannot open: block.
- No safe first-comment URL: block.

## Current Cadence

- Daily library refresh and rerank: 02:20 Asia/Taipei.
- Posting cadence target: one candidate every 6 hours.
- Preferred posting slots: 01:40, 07:40, 13:40, 19:40 Asia/Taipei. These avoid the current 03:00 YouTube patrol, 05:20 Facebook patrol, 06:30 YT/FB email report, 07:00 DYU brief, and 09:00 war-room report better than top-of-hour posting.

## Publication Guard

The 6-hour runner may prepare or publish only the next candidate whose status is `ready`.

Before clicking Facebook's final publish button, the runner must:

1. Re-open the selected VolPred article and confirm full text is readable.
2. Recheck duplicate status using cached results first, then live/external checks if cache is stale.
3. Confirm post body contains no `http`, `volpred.zeabur.app`, or raw article ID link.
4. Publish the post body through Chrome on Ivan Lai's personal profile.
5. Add the first comment with `全文：https://volpred.zeabur.app/v3/reports/{id}`.
6. Verify the post URL and comment are visible.
7. Update `posted-links.json`, `posting-library.json`, `posting-schedule.md`, and relevant profile/dashboard notes.

If any step fails, the item must move to `blocked` or `needs_review`, not silently skip to the next article.

## Text Composer Input Method

Successful test on 2026-06-10:

1. Use the already authenticated Ivan Lai Facebook home tab.
2. Click the visible composer text area by screen coordinate around `Ivan Lai，在想些什麼？`.
3. Wait until the `建立貼文` modal is open and the `textbox` is active.
4. Write the final draft to the tab clipboard.
5. Press `Meta+V`.
6. Verify the exact Chinese draft appears in the composer DOM and visually compare the first and last line.
7. Only then click `發佈`.

Do not switch a text-only VolPred article to Reel just because the first composer click fails. Reel is for video assets; VolPred article posts are text posts with the article URL in the first comment.
