import {useEffect, useMemo, useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import {
  Alert,
  Button,
  Card,
  Col,
  ConfigProvider,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Layout,
  message,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography
} from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import {
  getCrawlerStatus,
  getCrawlerTaskLog,
  getCrawlerTasks,
  getChartExportUrl,
  getChartTrends,
  getDashboardOverview,
  getDbHealth,
  getDbMaintenanceHistory,
  getModeComparison,
  getPlayerCompare,
  getPredefinedQueries,
  getPlugins,
  executeAdvancedQuery,
  getQualityCheckJob,
  getQualityReport,
  runCrawler,
  runDbMaintenance,
  runPlugin,
  startQualityCheckJob
} from "./api";
import {AppLocale, dictionaries} from "./i18n";

const { Header, Content } = Layout;

type CrawlerTaskRow = {
  task_id: string;
  crawler_type: string;
  status: string;
  started_at?: string;
  ended_at?: string;
};

type QualityIssueRow = {
  rule_id: string;
  severity: string;
  message: string;
  recommendation?: string;
};

type DBHistoryRow = {
  action: string;
  success: boolean;
  started_at: string;
  finished_at?: string;
};

type ActionLogRow = {
  id: string;
  time: string;
  scope: string;
  phase: string;
  detail: string;
  durationMs?: number;
};

type ActionContext = {
  id: string;
  startedAt: number;
  messageKey: string;
  scope: string;
  detail: string;
};

type SchemaProperty = {
  type?: string;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  default?: unknown;
  description?: string;
};

type PluginSchema = {
  type?: string;
  properties?: Record<string, SchemaProperty>;
};

type PluginRow = {
  id: string;
  name: string;
  version: string;
  capabilities?: string[];
  config_schema?: PluginSchema;
  run_schema?: PluginSchema;
};

type CrawlerFormValues = {
  crawler_type: "leaderboard" | "player" | "stb";
  once?: boolean;
  limit?: number;
  source?: string;
  rpm?: number;
  uid?: string;
  uid_range?: string;
  max_workers?: number;
  days_since_update?: number;
  from_db?: boolean;
  cid_crawl?: boolean;
  sid_crawl?: boolean;
  retry_failed?: boolean;
  start?: number;
  end?: number;
  resume?: boolean;
};

type QueryTemplateParameters = {
  table: string;
  columns?: string[];
  filters?: Array<Record<string, unknown>>;
  order_by?: string[];
  group_by?: string[];
  having?: Array<Record<string, unknown>>;
  limit?: number;
  offset?: number;
  distinct?: boolean;
};

type QueryTemplateDefinition = {
  description?: string;
  endpoint?: string;
  method?: string;
  parameters?: QueryTemplateParameters;
};

type QueryTemplateField = {
  name: string;
  labelKey: string;
  type: "text" | "number" | "select";
  min?: number;
  max?: number;
  placeholder?: string;
  options?: Array<{ value: string | number; label: string }>;
  defaultValue?: string | number;
};

type QueryTemplateUiConfig = {
  titleKey: string;
  descriptionKey: string;
  fields: QueryTemplateField[];
};

const QUERY_TEMPLATE_UI: Record<string, QueryTemplateUiConfig> = {
  top_players_by_mode: {
    titleKey: "query_template_top_players_title",
    descriptionKey: "query_template_top_players_desc",
    fields: [
      { name: "mode", labelKey: "mode", type: "number", min: 0, max: 9, placeholder: "0" },
      { name: "maxRank", labelKey: "query_field_max_rank", type: "number", min: 1, max: 100, defaultValue: 10 },
      { name: "limit", labelKey: "limit", type: "number", min: 1, max: 1000 }
    ]
  },
  chart_statistics_by_status: {
    titleKey: "query_template_chart_status_title",
    descriptionKey: "query_template_chart_status_desc",
    fields: [
      {
        name: "status",
        labelKey: "query_field_status",
        type: "select",
        defaultValue: 2,
        options: [
          { value: 0, label: "status=0" },
          { value: 1, label: "status=1" },
          { value: 2, label: "status=2" }
        ]
      }
    ]
  },
  player_ranking_history: {
    titleKey: "query_template_player_history_title",
    descriptionKey: "query_template_player_history_desc",
    fields: [
      { name: "playerName", labelKey: "query_field_player_name", type: "text", defaultValue: "Zani", placeholder: "Alice" },
      { name: "limit", labelKey: "limit", type: "number", min: 1, max: 1000 }
    ]
  },
  top_creators_by_stable_charts: {
    titleKey: "query_template_creator_title",
    descriptionKey: "query_template_creator_desc",
    fields: [
      { name: "creatorName", labelKey: "query_field_creator", type: "text", placeholder: "Alice" },
      { name: "limit", labelKey: "limit", type: "number", min: 1, max: 1000 }
    ]
  }
};

function cloneTemplateParams(params?: QueryTemplateParameters): QueryTemplateParameters {
  if (!params) {
    return { table: "", columns: [], filters: [], order_by: [], group_by: [], having: [], limit: 100, offset: 0, distinct: false };
  }
  return {
    table: String(params.table ?? ""),
    columns: [...(params.columns ?? [])],
    filters: [...(params.filters ?? [])],
    order_by: [...(params.order_by ?? [])],
    group_by: [...(params.group_by ?? [])],
    having: [...(params.having ?? [])],
    limit: params.limit,
    offset: params.offset,
    distinct: params.distinct
  };
}

function upsertFilter(
  filters: Array<Record<string, unknown>>,
  next: { field: string; operator: string; value?: unknown },
  removeWhenEmpty = false
): Array<Record<string, unknown>> {
  const out = filters.filter((item) => !(item.field === next.field && item.operator === next.operator));
  const isEmpty = next.value === undefined || next.value === null || next.value === "";
  if (!removeWhenEmpty || !isEmpty) {
    out.push({
      field: next.field,
      operator: next.operator,
      value: next.value ?? null
    });
  }
  return out;
}

function buildQueryPayloadFromTemplate(
  queryKey: string,
  definition: QueryTemplateDefinition | undefined,
  formValues: Record<string, unknown>
) {
  const params = cloneTemplateParams(definition?.parameters);
  let filters = [...(params.filters ?? [])];

  const limit = typeof formValues.limit === "number" ? formValues.limit : undefined;
  if (typeof limit === "number") {
    params.limit = limit;
  }

  if (queryKey === "top_players_by_mode") {
    if (typeof formValues.maxRank === "number") {
      filters = upsertFilter(filters, { field: "rank", operator: "<=", value: formValues.maxRank });
    }
    if (typeof formValues.mode === "number") {
      filters = upsertFilter(filters, { field: "mode", operator: "=", value: formValues.mode }, true);
    }
  }

  if (queryKey === "chart_statistics_by_status") {
    if (typeof formValues.status === "number") {
      filters = upsertFilter(filters, { field: "status", operator: "=", value: formValues.status }, true);
    }
  }

  if (queryKey === "player_ranking_history") {
    filters = upsertFilter(filters, { field: "name", operator: "LIKE", value: formValues.playerName }, true);
  }

  if (queryKey === "top_creators_by_stable_charts") {
    if (typeof formValues.creatorName === "string" && formValues.creatorName.trim()) {
      filters = upsertFilter(filters, { field: "creator_name", operator: "LIKE", value: formValues.creatorName.trim() });
    }
  }

  return {
    table: params.table,
    columns: params.columns ?? [],
    filters,
    order_by: params.order_by ?? [],
    group_by: params.group_by ?? [],
    having: params.having ?? [],
    limit: params.limit ?? 100,
    offset: params.offset ?? 0,
    distinct: Boolean(params.distinct)
  };
}

function exportRowsToCsv(rows: Record<string, unknown>[], filename: string) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const escapeCsv = (value: unknown): string => {
    const raw = String(value ?? "");
    if (raw.includes(",") || raw.includes('"') || raw.includes("\n")) {
      return `"${raw.replace(/"/g, '""')}"`;
    }
    return raw;
  };
  const lines = [headers.join(",")];
  rows.forEach((row) => {
    lines.push(headers.map((key) => escapeCsv(row[key])).join(","));
  });
  const blob = new Blob([`\uFEFF${lines.join("\n")}`], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

export function buildCrawlerRunParams(values: CrawlerFormValues): URLSearchParams {
  const params = new URLSearchParams();
  const crawlerType = values.crawler_type;
  params.set("crawler_type", crawlerType);

  if (crawlerType === "leaderboard") {
    params.set("once", String(values.once ?? true));
    if (values.limit) params.set("limit", String(values.limit));
    if (values.source) params.set("source", values.source);
    return params;
  }

  if (crawlerType === "player") {
    if (values.limit) params.set("limit", String(values.limit));
    if (values.rpm) params.set("rpm", String(values.rpm));
    if (values.uid) params.set("uid", String(values.uid));
    if (values.uid_range) params.set("uid_range", String(values.uid_range));
    if (values.max_workers) params.set("max_workers", String(values.max_workers));
    if (values.days_since_update) params.set("days_since_update", String(values.days_since_update));
    if (values.from_db) params.set("from_db", "true");
    return params;
  }

  params.set("once", String(values.once ?? true));
  if (values.limit) params.set("limit", String(values.limit));
  if (values.source) params.set("source", values.source);
  if (values.rpm) params.set("rpm", String(values.rpm));
  if (values.cid_crawl) params.set("cid_crawl", "true");
  if (values.sid_crawl) params.set("sid_crawl", "true");
  if (values.retry_failed) params.set("retry_failed", "true");
  if (values.start) params.set("start", String(values.start));
  if (values.end) params.set("end", String(values.end));
  if (values.resume === false) params.set("resume", "false");
  return params;
}

function App() {
  const queryClient = useQueryClient();
  const [queryTaskForm] = Form.useForm();
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [actionLogs, setActionLogs] = useState<ActionLogRow[]>([]);
  const [qualityJobId, setQualityJobId] = useState<string>("");
  const [qualityJobStatus, setQualityJobStatus] = useState<string>("");
  const [qualityJobNotifiedStatus, setQualityJobNotifiedStatus] = useState<string>("");
  const [crawlerType, setCrawlerType] = useState<"leaderboard" | "player" | "stb">("leaderboard");
  const [selectedPluginId, setSelectedPluginId] = useState<string>("");
  const [pluginPayload, setPluginPayload] = useState<Record<string, unknown>>({});
  const [selectedQueryKey, setSelectedQueryKey] = useState<string>("");
  const [queryResultRows, setQueryResultRows] = useState<Record<string, unknown>[]>([]);
  const [queryResultTitle, setQueryResultTitle] = useState<string>("");
  const [modeCompareRows, setModeCompareRows] = useState<Record<string, unknown>[]>([]);
  const [playerCompareRows, setPlayerCompareRows] = useState<Record<string, unknown>[]>([]);
  const [chartTrendRows, setChartTrendRows] = useState<Record<string, unknown>[]>([]);
  const [locale, setLocale] = useState<AppLocale>(() => {
    const raw = localStorage.getItem("app.locale");
    return raw === "en-US" || raw === "zh-CN" ? raw : "zh-CN";
  });

  const t = (key: string) => dictionaries[locale][key] ?? key;

  const formatError = (error: unknown): string => {
    return parseError(error).summary;
  };

  const parseError = (error: unknown): { summary: string; detail?: string } => {
    const raw = error instanceof Error ? error.message : String(error ?? t("error_unknown"));
    if (!raw) return { summary: t("error_unknown") };
    if (raw.includes("Request timeout")) {
      return { summary: t("error_timeout"), detail: raw };
    }
    if (raw.startsWith("HTTP ")) {
      const match = raw.match(/^HTTP\s+(\d+)\s+([^:]+):\s*(.*)$/);
      if (match) {
        const [, code, endpoint, detail] = match;
        return {
          summary: `${t("error_request_failed")} (HTTP ${code})`,
          detail: `${endpoint} - ${detail || raw}`
        };
      }
      return { summary: t("error_request_failed"), detail: raw };
    }
    return { summary: raw };
  };

  const scopeLabel = (scope: string): string => {
    const mapping: Record<string, string> = {
      overview: t("scope_overview"),
      "crawler-status": t("scope_crawler_status"),
      "crawler-tasks": t("scope_crawler_tasks"),
      "task-log": t("scope_task_log"),
      "quality-report": t("scope_quality_report"),
      "quality-job": t("scope_quality_job"),
      "db-health": t("scope_db_health"),
      "db-history": t("scope_db_history"),
      plugins: t("scope_plugins"),
      query: t("tab_query"),
      analytics: t("tab_analytics"),
      crawler: t("tab_crawler"),
      quality: t("tab_quality"),
      db: t("tab_db"),
      plugin: t("tab_plugins")
    };
    return mapping[scope] ?? scope;
  };

  const statusLabel = (status?: string): string => {
    const mapping: Record<string, string> = {
      queued: t("status_queued"),
      running: t("status_running"),
      finished: t("status_finished"),
      failed: t("status_failed"),
      started: t("op_started"),
      succeeded: t("op_succeeded")
    };
    if (!status) return "-";
    return mapping[status] ?? status;
  };

  const formatDuration = (ms?: number): string => {
    if (typeof ms !== "number" || Number.isNaN(ms)) return "-";
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(2)} s`;
  };

  const buildDefaultPayload = (schema?: PluginSchema): Record<string, unknown> => {
    const props = schema?.properties ?? {};
    const out: Record<string, unknown> = {};
    Object.entries(props).forEach(([key, def]) => {
      if (typeof def.default !== "undefined") {
        out[key] = def.default;
        return;
      }
      if (def.type === "boolean") out[key] = false;
      else if (def.type === "integer" || def.type === "number") out[key] = def.minimum ?? 0;
      else out[key] = "";
    });
    return out;
  };

  const toNumber = (value: unknown): number | undefined => {
    if (typeof value === "number") return value;
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (!Number.isNaN(parsed)) return parsed;
    }
    return undefined;
  };

  useEffect(() => {
    localStorage.setItem("app.locale", locale);
  }, [locale]);

  const addLog = (row: ActionLogRow) => {
    setActionLogs((prev) => [row, ...prev].slice(0, 200));
  };

  const startAction = (scope: string, detail: string, loadingText: string): ActionContext => {
    const startedAt = Date.now();
    const id = `${scope}-${startedAt}`;
    const messageKey = `msg-${id}`;
    addLog({
      id,
      time: new Date(startedAt).toLocaleString(),
      scope,
      phase: t("op_started"),
      detail
    });
    message.loading({ content: loadingText, key: messageKey, duration: 0 });
    return { id, startedAt, messageKey, scope, detail };
  };

  const finishAction = (ctx: ActionContext | undefined, phase: string, detail: string) => {
    if (!ctx) return;
    addLog({
      id: `${ctx.id}-${phase}-${Date.now()}`,
      time: new Date().toLocaleString(),
      scope: ctx.scope,
      phase,
      detail,
      durationMs: Date.now() - ctx.startedAt
    });
  };

  const overviewQuery = useQuery({
    queryKey: ["overview"],
    queryFn: getDashboardOverview,
    refetchInterval: 10_000
  });
  const crawlerStatusQuery = useQuery({
    queryKey: ["crawler-status"],
    queryFn: getCrawlerStatus,
    refetchInterval: 5_000
  });
  const tasksQuery = useQuery({
    queryKey: ["crawler-tasks"],
    queryFn: getCrawlerTasks,
    refetchInterval: 5_000
  });
  const taskLogQuery = useQuery({
    queryKey: ["crawler-task-log", selectedTaskId],
    queryFn: () => getCrawlerTaskLog(selectedTaskId, 200),
    enabled: !!selectedTaskId,
    refetchInterval: 3_000
  });
  const qualityQuery = useQuery({
    queryKey: ["quality-report"],
    queryFn: getQualityReport,
    refetchInterval: 20_000
  });
  const qualityJobQuery = useQuery({
    queryKey: ["quality-job", qualityJobId],
    queryFn: () => getQualityCheckJob(qualityJobId),
    enabled: !!qualityJobId,
    refetchInterval: (query) => {
      const st = (query.state.data as { status?: string } | undefined)?.status;
      if (!st || st === "queued" || st === "running") return 2000;
      return false;
    }
  });
  const dbHealthQuery = useQuery({
    queryKey: ["db-health"],
    queryFn: getDbHealth,
    refetchInterval: 20_000
  });
  const dbHistoryQuery = useQuery({
    queryKey: ["db-history"],
    queryFn: getDbMaintenanceHistory
  });
  const pluginsQuery = useQuery({
    queryKey: ["plugins"],
    queryFn: getPlugins
  });
  const predefinedQuery = useQuery({
    queryKey: ["query-predefined"],
    queryFn: getPredefinedQueries
  });
  const predefinedTemplates = useMemo(
    () => Object.entries((predefinedQuery.data ?? {}) as Record<string, QueryTemplateDefinition>),
    [predefinedQuery.data]
  );
  const selectedQueryDefinition = useMemo(
    () => predefinedTemplates.find(([key]) => key === selectedQueryKey)?.[1],
    [predefinedTemplates, selectedQueryKey]
  );
  const selectedQueryInitialValues = useMemo(() => {
    if (!selectedQueryKey) return {};
    const config = QUERY_TEMPLATE_UI[selectedQueryKey];
    const defaults: Record<string, unknown> = {};
    (config?.fields ?? []).forEach((field) => {
      if (typeof field.defaultValue !== "undefined") {
        defaults[field.name] = field.defaultValue;
      }
    });
    if (typeof selectedQueryDefinition?.parameters?.limit === "number") {
      defaults.limit = selectedQueryDefinition.parameters.limit;
    }
    return defaults;
  }, [selectedQueryKey, selectedQueryDefinition]);

  const runCrawlerMutation = useMutation({
    mutationFn: runCrawler,
    onMutate: () => startAction("crawler", t("start_crawler"), t("op_running_crawler")),
    onSuccess: async (_, __, ctx) => {
      message.success({ content: t("crawler_started"), key: ctx?.messageKey });
      finishAction(ctx, t("op_succeeded"), t("crawler_started"));
      await queryClient.invalidateQueries({ queryKey: ["crawler-tasks"] });
      await queryClient.invalidateQueries({ queryKey: ["crawler-status"] });
    },
    onError: (error: Error, _, ctx) => {
      const msg = formatError(error);
      message.error({ content: msg, key: ctx?.messageKey });
      finishAction(ctx, t("op_failed"), msg);
    }
  });

  const runQualityMutation = useMutation({
    mutationFn: startQualityCheckJob,
    onMutate: () => startAction("quality", t("run_quality_check"), t("op_running_quality")),
    onSuccess: (data, _, ctx) => {
      const jobId = data?.job_id as string | undefined;
      if (!jobId) {
        message.error({ content: "Quality job missing job_id", key: ctx?.messageKey });
        finishAction(ctx, t("op_failed"), "missing job_id");
        return;
      }
      setQualityJobId(jobId);
      setQualityJobStatus(String(data?.status ?? "queued"));
      setQualityJobNotifiedStatus("");
      message.info({ content: `${t("quality_job_submitted")}: job=${jobId}`, key: ctx?.messageKey });
      finishAction(ctx, t("op_succeeded"), `${t("quality_job_submitted")}: job=${jobId}`);
    },
    onError: (error: Error, _, ctx) => {
      const msg = formatError(error);
      message.error({ content: msg, key: ctx?.messageKey });
      finishAction(ctx, t("op_failed"), msg);
    }
  });

  const dbMaintainMutation = useMutation({
    mutationFn: ({ action, dryRun }: { action: "analyze" | "vacuum"; dryRun: boolean }) =>
      runDbMaintenance(action, true, dryRun),
    onMutate: (vars) => startAction("db", `${t("action")}: ${vars.action}`, t("op_running_maintain")),
    onSuccess: async (_, __, ctx) => {
      message.success({ content: t("maintain_done"), key: ctx?.messageKey });
      finishAction(ctx, t("op_succeeded"), t("maintain_done"));
      await queryClient.invalidateQueries({ queryKey: ["db-health"] });
      await queryClient.invalidateQueries({ queryKey: ["db-history"] });
    },
    onError: (error: Error, _, ctx) => {
      const msg = formatError(error);
      message.error({ content: msg, key: ctx?.messageKey });
      finishAction(ctx, t("op_failed"), msg);
    }
  });

  const pluginRunMutation = useMutation({
    mutationFn: ({ pluginId, payload }: { pluginId: string; payload: Record<string, unknown> }) =>
      runPlugin(pluginId, { payload }),
    onMutate: (vars) => startAction("plugin", vars.pluginId, t("op_running_plugin")),
    onSuccess: (_, __, ctx) => {
      message.success({ content: t("plugin_done"), key: ctx?.messageKey });
      finishAction(ctx, t("op_succeeded"), t("plugin_done"));
    },
    onError: (error: Error, _, ctx) => {
      const msg = formatError(error);
      message.error({ content: msg, key: ctx?.messageKey });
      finishAction(ctx, t("op_failed"), msg);
    }
  });

  const executeQueryMutation = useMutation({
    mutationFn: executeAdvancedQuery,
    onMutate: () => startAction("query", t("tab_query"), t("tab_query")),
    onSuccess: (data, _, ctx) => {
      const rows = Array.isArray(data) ? data : [];
      setQueryResultRows(rows);
      message.success({ content: `${t("run")}: ${rows.length} rows`, key: ctx?.messageKey });
      finishAction(ctx, t("op_succeeded"), `rows=${rows.length}`);
    },
    onError: (error: Error, _, ctx) => {
      const msg = formatError(error);
      message.error({ content: msg, key: ctx?.messageKey });
      finishAction(ctx, t("op_failed"), msg);
    }
  });

  const modeCompareMutation = useMutation({
    mutationFn: getModeComparison,
    onSuccess: (data) => setModeCompareRows(Array.isArray(data) ? data : [])
  });

  const playerCompareMutation = useMutation({
    mutationFn: ({ players, mode, days }: { players: string; mode: number; days: number }) =>
      getPlayerCompare(players, mode, days),
    onSuccess: (data) => setPlayerCompareRows((data?.players as Record<string, unknown>[]) ?? [])
  });

  const chartTrendMutation = useMutation({
    mutationFn: ({ mode, period }: { mode: number; period: "days" | "months" }) => getChartTrends(mode, period),
    onSuccess: (data) => setChartTrendRows(Array.isArray(data) ? data : [])
  });

  useEffect(() => {
    const snapshot = qualityJobQuery.data as
      | { status?: string; job_id?: string; error?: string; started_at?: string; finished_at?: string }
      | undefined;
    if (!snapshot?.status) return;
    setQualityJobStatus(snapshot.status);
    if (snapshot.status === qualityJobNotifiedStatus) return;

    if (snapshot.status === "queued" || snapshot.status === "running") {
      addLog({
        id: `quality-job-${snapshot.job_id}-${snapshot.status}-${Date.now()}`,
        time: new Date().toLocaleString(),
        scope: "quality",
        phase: statusLabel(snapshot.status),
        detail: `job=${snapshot.job_id}`
      });
      setQualityJobNotifiedStatus(snapshot.status);
      return;
    }

    if (snapshot.status === "finished") {
      const durationMs =
        snapshot.started_at && snapshot.finished_at
          ? Math.max(0, new Date(snapshot.finished_at).getTime() - new Date(snapshot.started_at).getTime())
          : undefined;
      message.success(t("quality_done"));
      addLog({
        id: `quality-job-${snapshot.job_id}-finished-${Date.now()}`,
        time: new Date().toLocaleString(),
        scope: "quality",
        phase: t("op_succeeded"),
        detail: `job=${snapshot.job_id}`,
        durationMs
      });
      queryClient.invalidateQueries({ queryKey: ["quality-report"] });
      setQualityJobNotifiedStatus(snapshot.status);
      return;
    }

    if (snapshot.status === "failed") {
      message.error(formatError(snapshot.error || "Quality check failed"));
      addLog({
        id: `quality-job-${snapshot.job_id}-failed-${Date.now()}`,
        time: new Date().toLocaleString(),
        scope: "quality",
        phase: t("op_failed"),
        detail: formatError(snapshot.error || `job=${snapshot.job_id}`)
      });
      setQualityJobNotifiedStatus(snapshot.status);
    }
  }, [qualityJobQuery.data, qualityJobNotifiedStatus, queryClient]);

  const taskRows: CrawlerTaskRow[] = tasksQuery.data?.tasks ?? [];
  const qualityIssues: QualityIssueRow[] = qualityQuery.data?.issues ?? [];
  const dbHistoryRows: DBHistoryRow[] = dbHistoryQuery.data?.history ?? [];
  const queryErrors = useMemo(
    () =>
      [
        { scope: "overview", error: overviewQuery.error as Error | null },
        { scope: "crawler-status", error: crawlerStatusQuery.error as Error | null },
        { scope: "crawler-tasks", error: tasksQuery.error as Error | null },
        { scope: "task-log", error: taskLogQuery.error as Error | null },
        { scope: "quality-report", error: qualityQuery.error as Error | null },
        { scope: "quality-job", error: qualityJobQuery.error as Error | null },
        { scope: "db-health", error: dbHealthQuery.error as Error | null },
        { scope: "db-history", error: dbHistoryQuery.error as Error | null },
        { scope: "plugins", error: pluginsQuery.error as Error | null },
        { scope: "query", error: predefinedQuery.error as Error | null }
      ].filter((item) => !!item.error),
    [
      overviewQuery.error,
      crawlerStatusQuery.error,
      tasksQuery.error,
      taskLogQuery.error,
      qualityQuery.error,
      qualityJobQuery.error,
      dbHealthQuery.error,
      dbHistoryQuery.error,
      pluginsQuery.error,
      predefinedQuery.error
    ]
  );

  const chartOption = useMemo(() => {
    const summary = crawlerStatusQuery.data?.tasks ?? {};
    return {
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["45%", "70%"],
          data: [
            { name: t("running"), value: summary.running ?? 0 },
            { name: t("finished_status"), value: summary.finished ?? 0 },
            { name: t("failed"), value: summary.failed ?? 0 }
          ]
        }
      ]
    };
  }, [crawlerStatusQuery.data, locale]);

  const plugins = (pluginsQuery.data?.plugins ?? []) as PluginRow[];
  const selectedPlugin = plugins.find((item) => item.id === selectedPluginId);

  useEffect(() => {
    if (!selectedPlugin) return;
    setPluginPayload(buildDefaultPayload(selectedPlugin.run_schema));
  }, [selectedPluginId, pluginsQuery.data]);

  useEffect(() => {
    if (!selectedQueryKey && predefinedTemplates.length > 0) {
      setSelectedQueryKey(predefinedTemplates[0][0]);
      return;
    }
    if (selectedQueryKey && !predefinedTemplates.some(([key]) => key === selectedQueryKey)) {
      setSelectedQueryKey(predefinedTemplates[0]?.[0] ?? "");
    }
  }, [predefinedTemplates, selectedQueryKey]);

  return (
    <ConfigProvider locale={locale === "zh-CN" ? zhCN : enUS}>
      <Layout className="app-shell">
        <Header className="app-header">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
            <Typography.Title level={3} style={{ color: "#fff", margin: 0 }}>
              {t("app_title")}
            </Typography.Title>
            <Space>
              <Typography.Text style={{ color: "#fff" }}>{t("lang_label")}</Typography.Text>
              <Select
                value={locale}
                style={{ width: 120 }}
                onChange={(value) => setLocale(value)}
                options={[
                  { value: "zh-CN", label: "中文" },
                  { value: "en-US", label: "English" }
                ]}
              />
            </Space>
          </div>
        </Header>
        <Content className="app-content">
          {queryErrors.length > 0 ? (
            <Alert
              type="error"
              showIcon
              message={t("query_error_summary")}
              description={
                <Space direction="vertical" size={4}>
                  {queryErrors.map((item) => {
                    const parsed = parseError(item.error);
                    return (
                      <div key={item.scope}>
                        <Typography.Text>
                          [{scopeLabel(item.scope)}] {parsed.summary}
                        </Typography.Text>
                        {parsed.detail ? (
                          <details style={{ marginTop: 4 }}>
                            <summary>{t("error_details")}</summary>
                            <Typography.Text type="secondary">{parsed.detail}</Typography.Text>
                          </details>
                        ) : null}
                      </div>
                    );
                  })}
                </Space>
              }
              style={{ marginBottom: 16 }}
            />
          ) : null}
          <Tabs
            items={[
              {
                key: "overview",
                label: t("tab_overview"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Row gutter={16}>
                      <Col span={6}>
                        <Card>
                          <Statistic
                            title={t("db_size_mb")}
                            value={((overviewQuery.data?.database?.file_size_bytes ?? 0) / (1024 * 1024)).toFixed(2)}
                          />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card>
                          <Statistic title={t("crawler_running")} value={crawlerStatusQuery.data?.tasks?.running ?? 0} />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card>
                          <Statistic title={t("crawler_failed")} value={crawlerStatusQuery.data?.tasks?.failed ?? 0} />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card>
                          <Statistic title={t("quality_score")} value={qualityQuery.data?.score ?? "-"} />
                        </Card>
                      </Col>
                    </Row>
                    <Card title={t("crawler_distribution")}>
                      <ReactECharts option={chartOption} style={{ height: 280 }} />
                    </Card>
                    <Card title={t("db_snapshot")}>
                      <Descriptions bordered column={2} size="small">
                        <Descriptions.Item label={t("path")}>{overviewQuery.data?.database?.path ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("fragmentation")}>
                          {overviewQuery.data?.database?.fragmentation_ratio ?? "-"}%
                        </Descriptions.Item>
                        <Descriptions.Item label={t("quick_check")}>
                          {overviewQuery.data?.database?.quick_check ?? "-"}
                        </Descriptions.Item>
                        <Descriptions.Item label="source_health">
                          {crawlerStatusQuery.data?.data_source_health?.overall ?? "-"}
                        </Descriptions.Item>
                        <Descriptions.Item label={t("generated_at")}>{overviewQuery.data?.generated_at ?? "-"}</Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </Space>
                )
              },
              {
                key: "analytics",
                label: t("tab_analytics"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Card title={t("analytics_mode_compare")}>
                      <Form
                        layout="inline"
                        onFinish={(values) => modeCompareMutation.mutate(values.modes)}
                        initialValues={{ modes: "0,1,2,3" }}
                      >
                        <Form.Item name="modes" label={t("modes")}>
                          <Input style={{ width: 220 }} placeholder="0,1,2" />
                        </Form.Item>
                        <Form.Item>
                          <Button htmlType="submit" loading={modeCompareMutation.isPending}>
                            {t("run")}
                          </Button>
                        </Form.Item>
                      </Form>
                      <Table
                        rowKey={(row: Record<string, unknown>) => String(row.mode ?? JSON.stringify(row))}
                        dataSource={modeCompareRows}
                        size="small"
                        pagination={{ pageSize: 6 }}
                        locale={{ emptyText: t("no_data") }}
                        columns={[
                          { title: "mode", dataIndex: "mode" },
                          { title: "total_charts", dataIndex: "total_charts" },
                          { title: "stable_charts", dataIndex: "stable_charts" },
                          { title: "avg_heat", dataIndex: "avg_heat" }
                        ]}
                      />
                    </Card>
                    <Card title={t("analytics_player_compare")}>
                      <Form
                        layout="inline"
                        onFinish={(values) =>
                          playerCompareMutation.mutate({
                            players: values.players,
                            mode: values.mode,
                            days: values.days
                          })
                        }
                        initialValues={{ players: "alice,bob", mode: 0, days: 30 }}
                      >
                        <Form.Item name="players" label={t("players")}>
                          <Input style={{ width: 220 }} placeholder="alice,bob" />
                        </Form.Item>
                        <Form.Item name="mode" label={t("mode")}>
                          <InputNumber min={0} max={9} />
                        </Form.Item>
                        <Form.Item name="days" label={t("days")}>
                          <InputNumber min={1} max={365} />
                        </Form.Item>
                        <Form.Item>
                          <Button htmlType="submit" loading={playerCompareMutation.isPending}>
                            {t("run")}
                          </Button>
                        </Form.Item>
                      </Form>
                      <Table
                        rowKey={(row: Record<string, unknown>) =>
                          String(row.player_identifier ?? row.name ?? JSON.stringify(row))
                        }
                        dataSource={playerCompareRows}
                        size="small"
                        pagination={{ pageSize: 6 }}
                        locale={{ emptyText: t("no_data") }}
                        columns={[
                          { title: "player", dataIndex: "player_identifier" },
                          { title: "start_rank", dataIndex: "start_rank" },
                          { title: "end_rank", dataIndex: "end_rank" },
                          { title: "rank_change", dataIndex: "rank_change" }
                        ]}
                      />
                    </Card>
                    <Card title={t("analytics_chart_trends")}>
                      <Form
                        layout="inline"
                        onFinish={(values) =>
                          chartTrendMutation.mutate({
                            mode: values.mode,
                            period: values.period
                          })
                        }
                        initialValues={{ mode: 0, period: "months" }}
                      >
                        <Form.Item name="mode" label={t("mode")}>
                          <InputNumber min={0} max={9} />
                        </Form.Item>
                        <Form.Item name="period" label={t("period")}>
                          <Select
                            options={[
                              { value: "days", label: "days" },
                              { value: "months", label: "months" }
                            ]}
                            style={{ width: 140 }}
                          />
                        </Form.Item>
                        <Form.Item>
                          <Button htmlType="submit" loading={chartTrendMutation.isPending}>
                            {t("run")}
                          </Button>
                        </Form.Item>
                      </Form>
                      <Table
                        rowKey={(row: Record<string, unknown>) => String(row.period ?? JSON.stringify(row))}
                        dataSource={chartTrendRows}
                        size="small"
                        pagination={{ pageSize: 6 }}
                        locale={{ emptyText: t("no_data") }}
                        columns={[
                          { title: "period", dataIndex: "period" },
                          { title: "total", dataIndex: "count" },
                          { title: "stable", dataIndex: "stable_count" }
                        ]}
                      />
                    </Card>
                  </Space>
                )
              },
              {
                key: "crawler",
                label: t("tab_crawler"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Card title={t("start_crawler")}>
                      <Form
                        layout="inline"
                        onFinish={(values) => {
                          const params = buildCrawlerRunParams(values as CrawlerFormValues);
                          runCrawlerMutation.mutate(params);
                        }}
                        initialValues={{ crawler_type: "leaderboard", once: true }}
                      >
                        <Form.Item name="crawler_type" label={t("type")}>
                          <Select
                            options={[
                              { value: "leaderboard", label: "leaderboard" },
                              { value: "player", label: "player" },
                              { value: "stb", label: "stb" }
                            ]}
                            style={{ width: 150 }}
                            onChange={(value: "leaderboard" | "player" | "stb") => setCrawlerType(value)}
                          />
                        </Form.Item>
                        <Form.Item name="source" label={t("source")}>
                          <Input placeholder={t("optional")} />
                        </Form.Item>
                        <Form.Item name="limit" label={t("limit")}>
                          <InputNumber min={1} />
                        </Form.Item>
                        <Form.Item name="rpm" label="rpm">
                          <InputNumber min={1} />
                        </Form.Item>
                        {crawlerType === "player" ? (
                          <>
                            <Form.Item name="uid" label="uid">
                              <Input style={{ width: 140 }} />
                            </Form.Item>
                            <Form.Item name="uid_range" label="uid_range">
                              <Input style={{ width: 140 }} placeholder="1000-2000" />
                            </Form.Item>
                            <Form.Item name="from_db" label="from_db">
                              <Select
                                style={{ width: 110 }}
                                options={[
                                  { value: false, label: "false" },
                                  { value: true, label: "true" }
                                ]}
                              />
                            </Form.Item>
                            <Form.Item name="max_workers" label="max_workers">
                              <InputNumber min={1} max={8} />
                            </Form.Item>
                            <Form.Item name="days_since_update" label="days_since_update">
                              <InputNumber min={1} />
                            </Form.Item>
                          </>
                        ) : null}
                        {crawlerType === "stb" ? (
                          <>
                            <Form.Item name="cid_crawl" label="cid_crawl">
                              <Select
                                style={{ width: 110 }}
                                options={[
                                  { value: false, label: "false" },
                                  { value: true, label: "true" }
                                ]}
                              />
                            </Form.Item>
                            <Form.Item name="sid_crawl" label="sid_crawl">
                              <Select
                                style={{ width: 110 }}
                                options={[
                                  { value: false, label: "false" },
                                  { value: true, label: "true" }
                                ]}
                              />
                            </Form.Item>
                            <Form.Item name="retry_failed" label="retry_failed">
                              <Select
                                style={{ width: 120 }}
                                options={[
                                  { value: false, label: "false" },
                                  { value: true, label: "true" }
                                ]}
                              />
                            </Form.Item>
                            <Form.Item name="start" label="start">
                              <InputNumber min={1} />
                            </Form.Item>
                            <Form.Item name="end" label="end">
                              <InputNumber min={1} />
                            </Form.Item>
                            <Form.Item name="resume" label="resume">
                              <Select
                                style={{ width: 110 }}
                                options={[
                                  { value: true, label: "true" },
                                  { value: false, label: "false" }
                                ]}
                              />
                            </Form.Item>
                          </>
                        ) : null}
                        <Form.Item>
                          <Button type="primary" htmlType="submit" loading={runCrawlerMutation.isPending}>
                            {t("run")}
                          </Button>
                        </Form.Item>
                      </Form>
                    </Card>
                    <Card title={t("task_list")}>
                      <Table<CrawlerTaskRow>
                        rowKey="task_id"
                        dataSource={taskRows}
                        pagination={{ pageSize: 8 }}
                        locale={{ emptyText: t("no_data") }}
                        onRow={(record: CrawlerTaskRow) => ({ onClick: () => setSelectedTaskId(record.task_id) })}
                        columns={[
                          { title: t("task_id"), dataIndex: "task_id" },
                          { title: t("type"), dataIndex: "crawler_type" },
                          {
                            title: t("status"),
                            dataIndex: "status",
                            render: (value: string) => (
                              <Tag color={value === "failed" ? "red" : value === "running" ? "blue" : "green"}>
                                {statusLabel(value)}
                              </Tag>
                            )
                          },
                          { title: t("started_at"), dataIndex: "started_at" },
                          { title: t("ended_at"), dataIndex: "ended_at" }
                        ]}
                      />
                    </Card>
                    <Card title={`${t("task_log")} ${selectedTaskId ? `(${selectedTaskId})` : ""}`}>
                      <Input.TextArea
                        rows={12}
                        value={(taskLogQuery.data?.lines ?? []).join("\n")}
                        placeholder={t("select_task_log")}
                        readOnly
                      />
                    </Card>
                  </Space>
                )
              },
              {
                key: "quality",
                label: t("tab_quality"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Card>
                      <Space>
                        <Button loading={runQualityMutation.isPending} onClick={() => runQualityMutation.mutate(72)}>
                          {t("run_quality_check")}
                        </Button>
                        {qualityJobId ? (
                          <Tag color={qualityJobStatus === "finished" ? "green" : qualityJobStatus === "failed" ? "red" : "blue"}>
                            job={qualityJobId} status={statusLabel(qualityJobStatus)}
                          </Tag>
                        ) : null}
                        <Tag color={qualityQuery.data?.severity === "high" ? "red" : "gold"}>
                          {t("severity")}: {qualityQuery.data?.severity ?? "-"}
                        </Tag>
                        <Tag color="blue">
                          {t("score")}: {qualityQuery.data?.score ?? "-"}
                        </Tag>
                        <Tag>
                          {t("trend")}: {qualityQuery.data?.trend ?? "-"}
                        </Tag>
                      </Space>
                    </Card>
                    <Card title={t("quality_issues")}>
                      <Table
                        rowKey={(row: QualityIssueRow) => `${row.rule_id}-${row.message}`}
                        dataSource={qualityIssues}
                        pagination={{ pageSize: 8 }}
                        locale={{ emptyText: t("no_data") }}
                        columns={[
                          { title: t("rule"), dataIndex: "rule_id" },
                          { title: t("severity"), dataIndex: "severity" },
                          { title: t("message"), dataIndex: "message" },
                          { title: t("recommendation"), dataIndex: "recommendation" }
                        ]}
                      />
                    </Card>
                  </Space>
                )
              },
              {
                key: "db",
                label: t("tab_db"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Card title={t("db_health")}>
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label={t("db_path")}>{dbHealthQuery.data?.db_path ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("size_mb")}>
                          {((dbHealthQuery.data?.file_size_bytes ?? 0) / (1024 * 1024)).toFixed(2)}
                        </Descriptions.Item>
                        <Descriptions.Item label={t("fragmentation")}>
                          {dbHealthQuery.data?.fragmentation_ratio ?? "-"}%
                        </Descriptions.Item>
                        <Descriptions.Item label={t("quick_check")}>{dbHealthQuery.data?.quick_check ?? "-"}</Descriptions.Item>
                      </Descriptions>
                      <Space style={{ marginTop: 12 }}>
                        <Button
                          onClick={() => {
                            if (window.confirm(t("confirm_analyze"))) {
                              dbMaintainMutation.mutate({ action: "analyze", dryRun: false });
                            }
                          }}
                          loading={dbMaintainMutation.isPending}
                        >
                          {t("run_analyze")}
                        </Button>
                        <Button
                          danger
                          onClick={() => {
                            if (window.confirm(t("confirm_vacuum"))) {
                              dbMaintainMutation.mutate({ action: "vacuum", dryRun: false });
                            }
                          }}
                          loading={dbMaintainMutation.isPending}
                        >
                          {t("run_vacuum")}
                        </Button>
                        <Button onClick={() => dbMaintainMutation.mutate({ action: "analyze", dryRun: true })}>{t("dry_run")}</Button>
                      </Space>
                    </Card>
                    <Card title={t("maintain_history")}>
                      <Table<DBHistoryRow>
                        rowKey={(row: DBHistoryRow) => `${row.action}-${row.started_at}`}
                        dataSource={dbHistoryRows}
                        pagination={{ pageSize: 8 }}
                        locale={{ emptyText: t("no_data") }}
                        columns={[
                          { title: t("action"), dataIndex: "action" },
                          { title: t("success"), dataIndex: "success", render: (v: boolean) => String(v) },
                          { title: t("started_at"), dataIndex: "started_at" },
                          { title: t("finished"), dataIndex: "finished_at" }
                        ]}
                      />
                    </Card>
                  </Space>
                )
              },
              {
                key: "plugins",
                label: t("tab_plugins"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Alert type="info" message={t("plugin_hint_title")} description={t("plugin_hint_desc")} />
                    <Table
                      rowKey="id"
                      dataSource={plugins}
                      pagination={false}
                      locale={{ emptyText: t("no_data") }}
                      columns={[
                        { title: "ID", dataIndex: "id" },
                        { title: "Name", dataIndex: "name" },
                        { title: "Version", dataIndex: "version" },
                        {
                          title: t("capabilities"),
                          dataIndex: "capabilities",
                          render: (caps: string[]) => <Space>{(caps ?? []).map((cap) => <Tag key={cap}>{cap}</Tag>)}</Space>
                        },
                        {
                          title: t("action"),
                          render: (_, row: PluginRow) => (
                            <Button size="small" onClick={() => setSelectedPluginId(row.id)}>
                              {t("config")}
                            </Button>
                          )
                        }
                      ]}
                    />
                    {selectedPlugin ? (
                      <Card title={`${t("plugin_runner")}: ${selectedPlugin.name}`}>
                        <Space direction="vertical" style={{ width: "100%" }}>
                          {Object.entries(selectedPlugin.run_schema?.properties ?? {}).map(([key, schema]) => {
                            const value = pluginPayload[key];
                            if (schema.type === "boolean") {
                              return (
                                <Space key={key}>
                                  <Typography.Text>{key}</Typography.Text>
                                  <Select
                                    style={{ width: 160 }}
                                    value={Boolean(value)}
                                    options={[
                                      { value: true, label: "true" },
                                      { value: false, label: "false" }
                                    ]}
                                    onChange={(next) => setPluginPayload((prev) => ({ ...prev, [key]: next }))}
                                  />
                                </Space>
                              );
                            }
                            if (schema.type === "integer" || schema.type === "number") {
                              return (
                                <Space key={key}>
                                  <Typography.Text>{key}</Typography.Text>
                                  <InputNumber
                                    min={schema.minimum}
                                    max={schema.maximum}
                                    value={toNumber(value)}
                                    onChange={(next) => setPluginPayload((prev) => ({ ...prev, [key]: next ?? 0 }))}
                                  />
                                </Space>
                              );
                            }
                            if ((schema.enum ?? []).length > 0) {
                              return (
                                <Space key={key}>
                                  <Typography.Text>{key}</Typography.Text>
                                  <Select
                                    style={{ width: 220 }}
                                    value={String(value ?? "")}
                                    options={(schema.enum ?? []).map((item) => ({ value: item, label: item }))}
                                    onChange={(next) => setPluginPayload((prev) => ({ ...prev, [key]: next }))}
                                  />
                                </Space>
                              );
                            }
                            return (
                              <Space key={key}>
                                <Typography.Text>{key}</Typography.Text>
                                <Input
                                  style={{ width: 260 }}
                                  value={String(value ?? "")}
                                  onChange={(e) => setPluginPayload((prev) => ({ ...prev, [key]: e.target.value }))}
                                />
                              </Space>
                            );
                          })}
                          <Space>
                            <Button
                              type="primary"
                              loading={pluginRunMutation.isPending}
                              onClick={() =>
                                pluginRunMutation.mutate({
                                  pluginId: selectedPlugin.id,
                                  payload: pluginPayload
                                })
                              }
                            >
                              {t("run")}
                            </Button>
                            <Button onClick={() => setPluginPayload(buildDefaultPayload(selectedPlugin.run_schema))}>
                              {t("reset")}
                            </Button>
                          </Space>
                        </Space>
                      </Card>
                    ) : null}
                    {pluginRunMutation.data ? (
                      <Card title={t("latest_plugin_result")}>
                        <pre>{JSON.stringify(pluginRunMutation.data, null, 2)}</pre>
                      </Card>
                    ) : null}
                  </Space>
                )
              },
              {
                key: "query",
                label: t("tab_query"),
                children: (
                  <Space direction="vertical" style={{ width: "100%" }} size={16}>
                    <Alert type="info" message={t("query_workflow_title")} description={t("query_workflow_desc")} />
                    <Row gutter={16}>
                      <Col xs={24} lg={9}>
                        <Card title={t("query_task_templates")}>
                          <Space direction="vertical" style={{ width: "100%" }} size={10}>
                            {predefinedTemplates.map(([key, queryDef]) => {
                              const config = QUERY_TEMPLATE_UI[key];
                              return (
                                <Card key={key} size="small" style={selectedQueryKey === key ? { borderColor: "#1677ff" } : undefined}>
                                  <Space direction="vertical" style={{ width: "100%" }} size={8}>
                                    <Typography.Text strong>{t(config?.titleKey ?? key)}</Typography.Text>
                                    <Typography.Text type="secondary">
                                      {t(config?.descriptionKey ?? "query_template_generic_desc")}
                                    </Typography.Text>
                                    <Space size={6} wrap>
                                      <Tag>{String(queryDef.parameters?.table ?? "-")}</Tag>
                                      <Tag>{`limit=${String(queryDef.parameters?.limit ?? 100)}`}</Tag>
                                    </Space>
                                    <Button
                                      block
                                      type={selectedQueryKey === key ? "primary" : "default"}
                                      onClick={() => setSelectedQueryKey(key)}
                                    >
                                      {t("query_use_template")}
                                    </Button>
                                  </Space>
                                </Card>
                              );
                            })}
                            {predefinedTemplates.length === 0 ? <Typography.Text type="secondary">{t("no_data")}</Typography.Text> : null}
                          </Space>
                        </Card>
                      </Col>
                      <Col xs={24} lg={15}>
                        <Card title={t("query_task_runner")}>
                          {selectedQueryKey ? (
                            <Space direction="vertical" style={{ width: "100%" }} size={12}>
                              <Typography.Text strong>
                                {t(QUERY_TEMPLATE_UI[selectedQueryKey]?.titleKey ?? selectedQueryKey)}
                              </Typography.Text>
                              <Typography.Text type="secondary">
                                {t(QUERY_TEMPLATE_UI[selectedQueryKey]?.descriptionKey ?? "query_template_generic_desc")}
                              </Typography.Text>
                              <Form
                                key={selectedQueryKey}
                                form={queryTaskForm}
                                layout="vertical"
                                initialValues={selectedQueryInitialValues}
                                onFinish={(values) => {
                                  const payload = buildQueryPayloadFromTemplate(selectedQueryKey, selectedQueryDefinition, values);
                                  setQueryResultTitle(t(QUERY_TEMPLATE_UI[selectedQueryKey]?.titleKey ?? selectedQueryKey));
                                  executeQueryMutation.mutate(payload);
                                }}
                              >
                                <Row gutter={12}>
                                  {(QUERY_TEMPLATE_UI[selectedQueryKey]?.fields ?? []).map((field) => (
                                    <Col span={12} key={field.name}>
                                      <Form.Item name={field.name} label={t(field.labelKey)}>
                                        {field.type === "number" ? (
                                          <InputNumber min={field.min} max={field.max} style={{ width: "100%" }} />
                                        ) : field.type === "select" ? (
                                          <Select options={field.options ?? []} />
                                        ) : (
                                          <Input placeholder={field.placeholder} />
                                        )}
                                      </Form.Item>
                                    </Col>
                                  ))}
                                </Row>
                                <Space>
                                  <Button type="primary" htmlType="submit" loading={executeQueryMutation.isPending}>
                                    {t("query_run_task")}
                                  </Button>
                                  <Button onClick={() => queryTaskForm.resetFields()}>{t("reset")}</Button>
                                </Space>
                              </Form>
                            </Space>
                          ) : (
                            <Typography.Text type="secondary">{t("no_data")}</Typography.Text>
                          )}
                        </Card>
                        <Card title={t("query_export")} style={{ marginTop: 16 }}>
                          <Form
                            layout="inline"
                            onFinish={(values) => {
                              const statuses = Array.isArray(values.statuses)
                                ? values.statuses.map((item: string | number) => String(item)).join(",")
                                : undefined;
                              const url = getChartExportUrl({
                                mode: typeof values.mode === "number" ? values.mode : undefined,
                                creators: values.creators,
                                statuses,
                                format: values.format
                              });
                              window.open(url, "_blank");
                            }}
                            initialValues={{ format: "csv", statuses: [2] }}
                          >
                            <Form.Item name="mode" label={t("mode")}>
                              <InputNumber min={0} max={9} />
                            </Form.Item>
                            <Form.Item name="creators" label={t("query_field_creator")}>
                              <Input style={{ width: 180 }} placeholder="Alice,Bob" />
                            </Form.Item>
                            <Form.Item name="statuses" label={t("query_field_status")}>
                              <Select
                                mode="multiple"
                                style={{ width: 180 }}
                                options={[
                                  { value: 0, label: "0" },
                                  { value: 1, label: "1" },
                                  { value: 2, label: "2" }
                                ]}
                              />
                            </Form.Item>
                            <Form.Item name="format" label="format">
                              <Select
                                style={{ width: 120 }}
                                options={[
                                  { value: "csv", label: "csv" },
                                  { value: "xlsx", label: "xlsx" }
                                ]}
                              />
                            </Form.Item>
                            <Form.Item>
                              <Button htmlType="submit">{t("export")}</Button>
                            </Form.Item>
                          </Form>
                        </Card>
                      </Col>
                    </Row>
                    <Card
                      title={`${t("query_result")} ${queryResultTitle ? `(${queryResultTitle})` : ""}`}
                      extra={
                        <Button
                          size="small"
                          disabled={queryResultRows.length === 0}
                          onClick={() => exportRowsToCsv(queryResultRows, "query_result.csv")}
                        >
                          {t("query_export_result_csv")}
                        </Button>
                      }
                    >
                      <Space style={{ marginBottom: 12 }}>
                        <Tag>{`${t("query_rows_count")}: ${queryResultRows.length}`}</Tag>
                        <Tag>{`${t("query_columns_count")}: ${Object.keys(queryResultRows[0] ?? {}).length}`}</Tag>
                      </Space>
                      <Table
                        rowKey={(row: Record<string, unknown>) => String(Object.values(row).join("|"))}
                        dataSource={queryResultRows}
                        pagination={{ pageSize: 8 }}
                        locale={{ emptyText: t("no_data") }}
                        columns={Object.keys(queryResultRows[0] ?? {}).map((key) => ({
                          title: key,
                          dataIndex: key,
                          render: (value: unknown) => String(value ?? "")
                        }))}
                      />
                    </Card>
                  </Space>
                )
              }
            ]}
          />
          <Card
            title={t("op_logs")}
            style={{ marginTop: 16 }}
            extra={
              <Button size="small" onClick={() => setActionLogs([])}>
                {t("op_clear")}
              </Button>
            }
          >
            <Table<ActionLogRow>
              rowKey="id"
              size="small"
              dataSource={actionLogs}
              pagination={{ pageSize: 8 }}
              locale={{ emptyText: t("no_data") }}
              columns={[
                { title: t("op_time"), dataIndex: "time", width: 190 },
                { title: t("op_scope"), dataIndex: "scope", width: 120, render: (value: string) => scopeLabel(value) },
                { title: t("op_phase"), dataIndex: "phase", width: 120, render: (value: string) => statusLabel(value) },
                { title: t("op_detail"), dataIndex: "detail" },
                { title: t("op_duration"), dataIndex: "durationMs", width: 120, render: (value?: number) => formatDuration(value) }
              ]}
            />
          </Card>
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
