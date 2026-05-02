import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {API_BASE, getPlugins, getQualityCheckJob, runDbMaintenance, startQualityCheckJob} from "./api";

describe("api request edge cases", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("formats error with path and status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ success: false, error: "boom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(runDbMaintenance("analyze")).rejects.toThrow(
      "HTTP 500 /system/db/maintain?action=analyze&confirm=true&dry_run=false: boom"
    );
  });

  it("calls async quality start endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { job_id: "j1", status: "queued" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    const out = await startQualityCheckJob(72);
    expect(out.job_id).toBe("j1");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `${API_BASE}/quality/check?stale_hours=72&async_mode=true`,
      expect.any(Object)
    );
  });

  it("calls quality job endpoint", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { job_id: "j1", status: "running" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const out = await getQualityCheckJob("j1");
    expect(out.status).toBe("running");
    expect(globalThis.fetch).toHaveBeenCalledWith(`${API_BASE}/quality/jobs/j1`, expect.any(Object));
  });

  it("returns timeout error with endpoint path", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => {
      return new Promise((_, reject) => {
        const signal = init?.signal as AbortSignal;
        signal.addEventListener("abort", () => {
          const abortError = new Error("aborted");
          Object.defineProperty(abortError, "name", { value: "AbortError" });
          reject(abortError);
        });
      });
    });

    const p = getQualityCheckJob("job-timeout");
    const assertion = expect(p).rejects.toThrow("Request timeout (10000ms): /quality/jobs/job-timeout");
    await vi.advanceTimersByTimeAsync(10_001);
    await assertion;
  });

  it("handles non-json error responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("internal error", {
        status: 500
      })
    );

    await expect(getPlugins()).rejects.toThrow("HTTP 500 /plugins: unknown error");
  });
});
