# FAILURES.md

Known failure modes, edge cases, and honest tradeoffs in this implementation.

---

## 1. In-flight DMs are lost on process restart

When a `process_dm_delivery` background task is executing and the Render instance restarts (e.g., a new deploy, an OOM kill, or Render's free tier spin-down), that task dies mid-execution. The `DMDelivery` row may be stuck in `"sending"` or `"queued"` status indefinitely with no mechanism to resume it.

**Condition:** Render restarts while a background task is active.  
**Effect:** That DM is never sent. It appears as `"queued"` in `/stats` forever, inflating the queued count.  
**Fix needed:** A startup reconciliation job that finds all rows in `"sending"` or `"queued"` older than N minutes and re-enqueues them.

---

## 2. comment.deleted cannot cancel in-flight DMs

When a `comment.deleted` event arrives, we cancel any delivery rows still in `"queued"` status. However, if the background task for that delivery has already started executing (status moved to `"sending"`), we cannot stop it — the DM will be sent even though the comment was deleted.

**Condition:** `comment.deleted` arrives within milliseconds of the `comment.created` background task starting.  
**Effect:** DM is sent for a deleted comment.  
**Fix needed:** Re-check delivery status inside `process_dm_delivery` before calling the API, and abort if the delivery has been cancelled.

---

## 3. Rate limiter is in-memory and per-process

The rate limiter (`services/rate_limiter.py`) is a module-level singleton that tracks request times in memory. With `WEB_CONCURRENCY=1` on Render this works correctly — 10 requests per 60 seconds are respected.

If Render is ever scaled to multiple workers (or multiple dyno instances), each process has its own independent rate limiter. Collectively they would send up to `10 × N` requests per 60 seconds, breaching the actual PseudoGram API limit and triggering cascading 429s.

**Condition:** Multiple worker processes or horizontal scale-out.  
**Fix needed:** Move rate limit tracking to a shared store (Redis, PostgreSQL advisory lock, or atomic counter).

---

## 4. Reconciliation does not retry failed reconcile polls

`reconcile_dm_delivery` polls `GET /v1/dm/{dm_id}` up to 5 times with 2-second gaps. If all 5 polls return `"queued"` (e.g., the PseudoGram API is slow), the delivery is left in `"accepted"` status with no further reconciliation. These deliveries show up as `"queued"` in `/stats` indefinitely, even if the DM eventually fails on PseudoGram's side.

**Condition:** DM takes more than ~10 seconds to reach a terminal status on PseudoGram.  
**Effect:** Delivery is never marked `"delivered"` or `"failed"`. Stats undercount `sent` and overcount `queued`.

---

## 5. No idempotency key on DM send

The PseudoGram API supports an optional `Idempotency-Key` header. We do not send one. If a 500 error is returned after the DM was already accepted server-side (a common failure mode), we retry and send the DM a second time to the same user.

**Condition:** PseudoGram returns 500 after internally accepting the DM.  
**Effect:** User receives duplicate DMs. This is not caught by our `UniqueConstraint`, which only prevents duplicate *database rows*, not duplicate API calls.  
**Fix needed:** Send `Idempotency-Key: {delivery.id}` on every `POST /v1/dm/send` call.
