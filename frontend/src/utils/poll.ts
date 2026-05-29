/**
 * Generic poll-until-done utility for Phase 8 async endpoints.
 *
 * The backend now returns 202 + a job id from `/guard-rules`,
 * `/analysis/discover`, and `/analysis/batch` (and `/analysis/quick`). Each
 * has a corresponding `GET /<endpoint>/{id}` route. This helper keeps the
 * polling logic (interval, timeout, abort, fetch error handling) in one
 * place so each hook only declares the URL + a "done?" predicate.
 */

export interface PollOptions {
  /** Milliseconds between successive GETs. Default 3000. */
  intervalMs?: number;
  /** Hard upper bound on total polling time. Default 5 min. */
  timeoutMs?: number;
  /** AbortSignal forwarded to fetch; cancels both fetch + the poll loop. */
  signal?: AbortSignal;
}

export class PollTimeoutError extends Error {
  constructor(message = "Polling timed out") {
    super(message);
    this.name = "PollTimeoutError";
  }
}

/**
 * Poll `GET url` every `intervalMs` until `isDone(data)` returns true, then
 * resolve with the final response body. Rejects if `timeoutMs` elapses or the
 * caller aborts via `signal`.
 *
 * Transient HTTP errors (`!resp.ok`) are silently retried — the worker may
 * not yet have written the row, or the GET may briefly 5xx. Permanent errors
 * are surfaced when the timeout finally fires.
 */
export async function pollUntilDone<T>(
  url: string,
  isDone: (data: T) => boolean,
  opts: PollOptions = {},
): Promise<T> {
  const intervalMs = opts.intervalMs ?? 3000;
  const timeoutMs = opts.timeoutMs ?? 5 * 60 * 1000;
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    if (opts.signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const resp = await fetch(url, { signal: opts.signal });
      if (!resp.ok) continue;
      const data = (await resp.json()) as T;
      if (isDone(data)) return data;
    } catch (err) {
      // Re-throw aborts; everything else is treated as transient.
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      // Silently retry — the worker may still be writing.
    }
  }
  throw new PollTimeoutError(
    `Polling ${url} timed out after ${Math.round(timeoutMs / 1000)}s`,
  );
}
