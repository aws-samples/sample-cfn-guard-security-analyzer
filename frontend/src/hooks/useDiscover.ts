import { useState, useCallback } from "react";
import { API_BASE_URL } from "../config";
import { pollUntilDone, PollTimeoutError } from "../utils/poll";

/** A single discovered CloudFormation resource. */
export interface DiscoveredResource {
  /** CFN resource type identifier, e.g. "AWS::S3::Bucket". */
  name: string;
  /** Absolute URL to the per-resource documentation page. */
  url: string;
}

export type DiscoverStatus = "idle" | "discovering" | "ready" | "error";

export interface UseDiscoverReturn {
  status: DiscoverStatus;
  resources: DiscoveredResource[];
  error: string | null;
  /** The index URL the most recent discover call ran against. */
  sourceUrl: string | null;
  /** Trigger discovery for a CFN service-index URL. */
  discover: (url: string) => Promise<void>;
  /** Reset back to idle (clears resources + error). */
  clear: () => void;
}

/**
 * Detect whether a URL looks like a CFN service-index page.
 *
 * Index pages have a path segment of the form `AWS_<Service>.html` (no slashes
 * or hyphens between AWS and Service). Per-resource pages match
 * `aws-resource-<service>-<resource>.html`. We only flag the obvious index
 * pattern; the discover endpoint itself accepts either URL shape so the
 * worst-case from a wrong guess is "user clicks the wrong button" — never an
 * SSRF or off-allowlist call.
 *
 * Exported for unit testing.
 */
export function looksLikeServiceIndexUrl(url: string): boolean {
  if (typeof url !== "string" || !url) return false;
  // Path can include `AWS_S3.html`, `AWS_EC2.html`, etc. The leading slash
  // and trailing `.html` are intentional — bare `AWS_S3` in the middle of a
  // longer path (extremely unlikely but possible) is not flagged.
  return /\/AWS_[A-Za-z0-9]+\.html(?:\?|#|$)/.test(url);
}

/**
 * Hook for the multi-resource discovery flow.
 *
 * `discover(url)` calls `POST /analysis/discover`. On success, populates the
 * `resources` list and transitions to `ready`. On error, surfaces a string
 * message in `error` and transitions to `error`. Use `clear()` to reset.
 */
export function useDiscover(): UseDiscoverReturn {
  const [status, setStatus] = useState<DiscoverStatus>("idle");
  const [resources, setResources] = useState<DiscoveredResource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);

  const discover = useCallback(async (url: string) => {
    setStatus("discovering");
    setError(null);
    setResources([]);
    setSourceUrl(url);

    // Phase 8 async pattern: POST returns 202 + discoveryId, then we poll
    // GET /analysis/discover/{discoveryId} until COMPLETED or FAILED. Up to
    // 5 min total (matches the worker Lambda's 15-min cap with margin).
    try {
      const resp = await fetch(`${API_BASE_URL}/analysis/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resourceUrl: url }),
      });

      if (!resp.ok && resp.status !== 202) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(
          detail.error || detail.message || `HTTP ${resp.status}`,
        );
      }

      const dispatched = await resp.json();
      const discoveryId: string | undefined = dispatched.discoveryId;
      if (!discoveryId) {
        // Backend may have returned an inline result if we ever revert;
        // surface gracefully.
        const list: DiscoveredResource[] = Array.isArray(dispatched.resources)
          ? (dispatched.resources as DiscoveredResource[])
          : [];
        setResources(list);
        setStatus("ready");
        return;
      }

      type DiscoverJob = {
        status: string;
        result?: { resources?: DiscoveredResource[] };
        error?: string;
      };

      const finalState = await pollUntilDone<DiscoverJob>(
        `${API_BASE_URL}/analysis/discover/${discoveryId}`,
        (d) => d.status === "COMPLETED" || d.status === "FAILED",
      );

      if (finalState.status === "FAILED") {
        throw new Error(finalState.error || "Discovery failed");
      }

      const list: DiscoveredResource[] = Array.isArray(finalState.result?.resources)
        ? (finalState.result!.resources as DiscoveredResource[])
        : [];
      setResources(list);
      setStatus("ready");
    } catch (err: unknown) {
      const msg =
        err instanceof PollTimeoutError
          ? "Discovery timed out after 5 minutes"
          : err instanceof DOMException && err.name === "AbortError"
            ? "Discovery aborted"
            : (err as Error).message || "Failed to discover resources";
      setError(msg);
      setStatus("error");
    }
  }, []);

  const clear = useCallback(() => {
    setStatus("idle");
    setResources([]);
    setError(null);
    setSourceUrl(null);
  }, []);

  return { status, resources, error, sourceUrl, discover, clear };
}
