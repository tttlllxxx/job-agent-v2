import { useEffect, useId, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, command, dateTime } from "./api";
import type { Goal, Run } from "./types";
import { useWork } from "./hooks";

const paths: Record<string, string> = {
  today: "M12 3v2m0 14v2M3 12h2m14 0h2M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  assistant: "M20 11a8 8 0 0 1-8 8H5l-3 2 1-6A8 8 0 1 1 20 11ZM7 9h8m-8 4h5",
  opportunities: "m16 16 5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
  applications: "M8 6V3h8v3M3 7h18v14H3V7Zm0 6h18m-11 0h4v3h-4Z",
  profile: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3a8 8 0 0 1 16 0v3",
  settings:
    "M9 3h6l1 4 4 1v7l-4 1-1 4H9l-1-4-4-1V8l4-1 1-4Zm6 9a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  close: "m6 6 12 12M6 18 18 6",
  menu: "M4 6h16M4 12h16M4 18h16",
  plus: "M12 5v14M5 12h14",
  file: "M5 3h9l5 5v13H5V3Zm9 0v6h5M9 13h6m-6 4h6",
  bell: "M5 16h14l-2-3V8a5 5 0 0 0-10 0v5l-2 3Zm5 4h4",
  check: "m5 12 4 4L19 6",
  spark: "m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2Z",
};
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] || paths.file} />
    </svg>
  );
}
export function Heading({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="jd-page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children}
    </div>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="v2-error" role="alert">
      <strong>
        {error instanceof Error ? error.message : String(error || "操作未完成")}
      </strong>
      {retry && (
        <button className="jd-outline-button" onClick={retry}>
          重试
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="jd-empty">
      <Icon name="file" size={28} />
      <h3>{title}</h3>
      {children}
    </div>
  );
}

const fieldLabels: Record<string, string> = {
  name: "名称",
  title: "标题",
  summary: "概述",
  checklist: "准备事项",
  questions: "需要准备的问题",
  missing: "待补充信息",
  requirements: "资格要求",
  graduation_text: "毕业条件",
  graduation_range: "毕业日期范围",
  days_per_week: "每周天数",
  duration_months: "实习月数",
  start_before: "最晚到岗",
  all_students: "全体在校生",
  source_conflicts: "来源差异",
  conflicted_fields: "待核对字段",
  date_anomalies: "日期核验提示",
  field: "条件",
  previous: "此前内容",
  incoming: "本次内容",
  source: "来源",
  url: "来源链接",
  status: "状态",
  error: "原因",
  message: "说明",
  count: "数量",
  job_ids: "岗位记录",
  coverage: "已检查来源",
  query: "搜索条件",
  queries: "搜索条件",
  started_at: "开始时间",
  finished_at: "完成时间",
  revision: "版本",
  label: "阶段",
  occurred_at: "完成时间",
  planned_at: "预约时间",
  state: "进展状态",
  created_at: "记录时间",
  description: "说明",
  version_ids: "材料版本",
  resume_ids: "基础简历版本",
  attachment_ids: "附件记录",
  answers: "实际使用的答案",
  source_kind: "来源类型",
  company: "公司",
  city: "地点",
  published_at: "发布时间",
  deadline_at: "截止时间",
  scope: "适用范围",
  content: "内容",
};
export function valueText(value: unknown): string {
  if (value == null || value === "") return "尚未确认";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(valueText).join("、") || "暂无";
  if (typeof value === "object")
    return Object.entries(value)
      .map(([key, item]) => `${fieldLabels[key] || key}：${valueText(item)}`)
      .join("；");
  const names: Record<string, string> = {
    completed: "已完成",
    failed: "失败",
    partial: "部分完成",
    restricted: "访问受限",
    planned: "未来预约",
    open: "开放",
    closed: "关闭",
    unknown: "待确认",
    healthy: "正常",
    official: "官网",
    platform: "招聘平台",
    community: "社区",
    web: "网页",
  };
  return names[String(value)] || String(value);
}
export function DetailsList({ data }: { data: unknown }) {
  if (!data || typeof data !== "object" || !Object.keys(data).length)
    return <p className="jd-subtle">暂无记录</p>;
  return (
    <dl className="v2-readable-data">
      {Object.entries(data).map(([key, value]) => (
        <div key={key}>
          <dt>{fieldLabels[key] || key}</dt>
          <dd>{valueText(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Modal({
  title,
  close,
  children,
  wide = false,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const element = ref.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`jd-modal ${wide ? "jd-modal-wide" : ""}`}
      aria-labelledby={id}
      onCancel={close}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="jd-modal-head">
        <h2 id={id}>{title}</h2>
        <button onClick={close} className="jd-icon-button" aria-label="关闭">
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function GoalSelect({
  goals,
  value,
  onChange,
}: {
  goals: Goal[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <label className="v2-goal-select">
      当前目标
      <select
        aria-label="当前求职目标"
        value={value || ""}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        <option value="" disabled>
          选择求职目标
        </option>
        {goals.map((goal) => (
          <option key={goal.id} value={goal.id}>
            {goal.name}
          </option>
        ))}
      </select>
    </label>
  );
}
export function RunNotice({
  runId,
  onFinished,
}: {
  runId: number;
  onFinished?: (run: Run) => void;
}) {
  const work = useWork();
  const query = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api<Run>(`/runs/${runId}`),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status || "")
        ? 700
        : false,
  });
  const last = useRef("");
  useEffect(() => {
    const run = query.data;
    if (
      run &&
      !["queued", "running"].includes(run.status) &&
      last.current !== run.updated_at
    ) {
      last.current = run.updated_at;
      onFinished?.(run);
    }
  }, [query.data, onFinished]);
  if (query.error)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  const run = query.data;
  if (!run)
    return (
      <div className="v2-run" role="status">
        正在读取任务…
      </div>
    );
  const names: Record<string, string> = {
    queued: "排队中",
    running: "执行中",
    waiting_user: "等待你处理",
    completed: "已完成",
    partial: "部分完成",
    failed: "执行失败",
    cancelled: "已中止",
    result_unknown: "结果待核对",
  };
  return (
    <details className="v2-run" open={run.status === "failed"}>
      <summary>
        <span className="jd-live-dot" />
        {names[run.status] || run.status}
        <small>
          任务 #{run.id} · {dateTime(run.updated_at)}
        </small>
      </summary>
      {run.error && <ErrorNotice error={run.error} />}
      {!!work.error && <ErrorNotice error={work.error} />}
      <div className="v2-run-events">
        {run.events?.map((event) => (
          <div key={event.id}>
            <small>{dateTime(event.created_at)}</small>
            <span>
              {String(event.data.message || event.data.tool || event.type)}
            </span>
          </div>
        ))}
      </div>
      <div className="v2-actions">
        {["queued", "running"].includes(run.status) && (
          <button
            disabled={work.busy}
            onClick={() =>
              void work.perform(() => command(`/runs/${run.id}/cancel`))
            }
          >
            中止任务
          </button>
        )}
        {["failed", "partial", "waiting_user"].includes(run.status) && (
          <button
            disabled={work.busy}
            onClick={() =>
              void work.perform(() => command(`/runs/${run.id}/resume`))
            }
          >
            从记录继续
          </button>
        )}
        <Link to="/runs">全部运行记录</Link>
      </div>
    </details>
  );
}
