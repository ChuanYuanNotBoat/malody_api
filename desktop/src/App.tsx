import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message
} from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import {
  getCrawlerStatus,
  getCrawlerTaskLog,
  getCrawlerTasks,
  getDashboardOverview,
  getDbHealth,
  getDbMaintenanceHistory,
  getPlugins,
  getQualityCheckJob,
  getQualityReport,
  runCrawler,
  runDbMaintenance,
  runPlugin,
  startQualityCheckJob
} from "./api";
import { AppLocale, dictionaries } from "./i18n";

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

function App() {
  const queryClient = useQueryClient();
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [actionLogs, setActionLogs] = useState<ActionLogRow[]>([]);
  const [qualityJobId, setQualityJobId] = useState<string>("");
  const [qualityJobStatus, setQualityJobStatus] = useState<string>("");
  const [qualityJobNotifiedStatus, setQualityJobNotifiedStatus] = useState<string>("");
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
    mutationFn: ({ pluginId }: { pluginId: string }) =>
      runPlugin(pluginId, { payload: { stale_hours: 72, include_history: true } }),
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
        { scope: "plugins", error: pluginsQuery.error as Error | null }
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
      pluginsQuery.error
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
                        <Descriptions.Item label={t("generated_at")}>{overviewQuery.data?.generated_at ?? "-"}</Descriptions.Item>
                      </Descriptions>
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
                          const params = new URLSearchParams();
                          params.set("crawler_type", values.crawler_type);
                          params.set("once", String(values.once ?? true));
                          if (values.limit) params.set("limit", String(values.limit));
                          if (values.source) params.set("source", values.source);
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
                          />
                        </Form.Item>
                        <Form.Item name="source" label={t("source")}>
                          <Input placeholder={t("optional")} />
                        </Form.Item>
                        <Form.Item name="limit" label={t("limit")}>
                          <InputNumber min={1} />
                        </Form.Item>
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
                      dataSource={pluginsQuery.data?.plugins ?? []}
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
                          render: (_, row: { id: string }) => (
                            <Button size="small" loading={pluginRunMutation.isPending} onClick={() => pluginRunMutation.mutate({ pluginId: row.id })}>
                              {t("run")}
                            </Button>
                          )
                        }
                      ]}
                    />
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
                  <Card>
                    <Typography.Paragraph>{t("query_placeholder")}</Typography.Paragraph>
                  </Card>
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


