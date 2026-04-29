export const API_BASE = "http://127.0.0.1:18765";
const REQUEST_TIMEOUT_MS = 20_000;

type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  message?: string;
  error?: string;
  timestamp?: string;
};

type RequestOptions = RequestInit & { timeoutMs?: number };

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
      signal: controller.signal
    });
  } catch (error) {
    clearTimeout(timeout);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Request timeout (${timeoutMs}ms): ${path}`);
    }
    throw error;
  }

  clearTimeout(timeout);

  let json: ApiEnvelope<T> | null = null;
  try {
    json = (await response.json()) as ApiEnvelope<T>;
  } catch {
    json = null;
  }

  if (!response.ok || !json || !json.success) {
    const detail = json?.error || json?.message || "unknown error";
    throw new Error(`HTTP ${response.status} ${path}: ${detail}`);
  }
  return json.data as T;
}

export async function getDashboardOverview() {
  return request<any>("/analytics/dashboard-overview");
}

export async function getCrawlerStatus() {
  return request<any>("/crawler/status");
}

export async function getCrawlerTasks() {
  return request<any>("/crawler/tasks?limit=50");
}

export async function runCrawler(params: URLSearchParams) {
  return request<any>(`/crawler/run?${params.toString()}`, { method: "POST" });
}

export async function getCrawlerTaskLog(taskId: string, tail = 200) {
  return request<any>(`/crawler/tasks/${encodeURIComponent(taskId)}/log?tail=${tail}`);
}

export async function getQualityReport() {
  return request<any>("/quality/report");
}

export async function runQualityCheck(staleHours = 72) {
  return request<any>(`/quality/check?stale_hours=${staleHours}`, {
    method: "POST",
    body: "null"
  });
}

export async function startQualityCheckJob(staleHours = 72) {
  return request<any>(`/quality/check?stale_hours=${staleHours}&async_mode=true`, {
    method: "POST",
    body: "null",
    timeoutMs: 10_000
  });
}

export async function getQualityCheckJob(jobId: string) {
  return request<any>(`/quality/jobs/${encodeURIComponent(jobId)}`, {
    timeoutMs: 10_000
  });
}

export async function getPlugins() {
  return request<any>("/plugins");
}

export async function runPlugin(pluginId: string, payload?: Record<string, unknown>) {
  return request<any>(`/plugins/${encodeURIComponent(pluginId)}/run`, {
    method: "POST",
    body: JSON.stringify(payload ?? {})
  });
}

export async function getDbHealth() {
  return request<any>("/system/db/health");
}

export async function runDbMaintenance(action: "analyze" | "vacuum", confirm = true, dryRun = false) {
  return request<any>(
    `/system/db/maintain?action=${action}&confirm=${String(confirm)}&dry_run=${String(dryRun)}`,
    { method: "POST" }
  );
}

export async function getDbMaintenanceHistory() {
  return request<any>("/system/db/maintain/history?limit=20");
}
