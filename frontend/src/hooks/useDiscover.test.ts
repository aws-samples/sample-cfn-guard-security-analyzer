import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useDiscover, looksLikeServiceIndexUrl } from "./useDiscover";

const ORIGINAL_FETCH = globalThis.fetch;

beforeEach(() => {
  // Phase 8 async pattern uses pollUntilDone which sleeps 3s between GETs.
  // Fake timers + real-time skips keep the test suite fast.
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
});

describe("looksLikeServiceIndexUrl", () => {
  it("matches AWS_<Service>.html paths", () => {
    expect(
      looksLikeServiceIndexUrl(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html",
      ),
    ).toBe(true);
    expect(
      looksLikeServiceIndexUrl(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_EC2.html",
      ),
    ).toBe(true);
    expect(
      looksLikeServiceIndexUrl(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html?foo=bar",
      ),
    ).toBe(true);
  });

  it("does not match per-resource pages", () => {
    expect(
      looksLikeServiceIndexUrl(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html",
      ),
    ).toBe(false);
  });

  it("returns false for empty or non-string input", () => {
    expect(looksLikeServiceIndexUrl("")).toBe(false);
    // @ts-expect-error testing non-string runtime input
    expect(looksLikeServiceIndexUrl(null)).toBe(false);
    // @ts-expect-error testing non-string runtime input
    expect(looksLikeServiceIndexUrl(123)).toBe(false);
  });
});

describe("useDiscover — async pattern", () => {
  it("dispatches + polls until COMPLETED then exposes resources", async () => {
    const fakeResources = [
      { name: "AWS::S3::Bucket", url: "https://docs.aws.amazon.com/x/a.html" },
      { name: "AWS::S3::BucketPolicy", url: "https://docs.aws.amazon.com/x/b.html" },
    ];

    const fetchMock = vi.fn();
    // POST returns 202 + discoveryId
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 202,
      json: () => Promise.resolve({ discoveryId: "d-1", status: "IN_PROGRESS" }),
    } as Response);
    // First poll: still in progress
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: "IN_PROGRESS" }),
    } as Response);
    // Second poll: COMPLETED
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "COMPLETED",
          result: { resources: fakeResources, count: 2 },
        }),
    } as Response);
    globalThis.fetch = fetchMock;

    const { result } = renderHook(() => useDiscover());
    expect(result.current.status).toBe("idle");

    let discoverPromise: Promise<void> | undefined;
    act(() => {
      discoverPromise = result.current.discover(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html",
      );
    });
    await act(async () => {
      await vi.runAllTimersAsync();
      await discoverPromise;
    });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.resources).toEqual(fakeResources);
    expect(result.current.error).toBeNull();
  });

  it("clear() resets status, resources, error, and sourceUrl", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 202,
      json: () => Promise.resolve({ discoveryId: "d-2", status: "IN_PROGRESS" }),
    } as Response);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "COMPLETED",
          result: { resources: [], count: 0 },
        }),
    } as Response);
    globalThis.fetch = fetchMock;

    const { result } = renderHook(() => useDiscover());
    let p: Promise<void> | undefined;
    act(() => {
      p = result.current.discover(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html",
      );
    });
    await act(async () => {
      await vi.runAllTimersAsync();
      await p;
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.clear());
    expect(result.current.status).toBe("idle");
    expect(result.current.resources).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.sourceUrl).toBeNull();
  });
});

describe("useDiscover — error path", () => {
  it("surfaces validation error from POST 4xx", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ error: "resourceUrl hostname not allowed" }),
    } as Response);

    const { result } = renderHook(() => useDiscover());
    await act(async () => {
      await result.current.discover("http://attacker.example.com/AWS_S3.html");
    });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("resourceUrl hostname not allowed");
  });

  it("surfaces FAILED status from polling", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 202,
      json: () => Promise.resolve({ discoveryId: "d-3", status: "IN_PROGRESS" }),
    } as Response);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: "FAILED", error: "agent timeout" }),
    } as Response);
    globalThis.fetch = fetchMock;

    const { result } = renderHook(() => useDiscover());
    let p: Promise<void> | undefined;
    act(() => {
      p = result.current.discover(
        "https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html",
      );
    });
    await act(async () => {
      await vi.runAllTimersAsync();
      await p;
    });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("agent timeout");
  });
});
