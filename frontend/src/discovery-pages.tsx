import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api, command, dateTime, operationId } from "./api";
import {
  Empty,
  ErrorNotice,
  GoalSelect,
  Heading,
  Icon,
  RunNotice,
  DetailsList,
  valueText,
} from "./components";
import { useWork } from "./hooks";
import type {
  Action,
  Application,
  Goal,
  Inbox,
  Job,
  Page,
  Resume,
  Run,
  Subscription,
  Thread,
} from "./types";

export type GoalContext = {
  goals: Goal[];
  goalId: number | null;
  setGoalId: (id: number) => void;
};
const resultNames: Record<string, string> = {
  pass: "符合",
  fail: "不符合",
  unknown: "待确认",
};
export function JobRows({
  jobs,
  goalId,
}: {
  jobs: Job[];
  goalId: number | null;
}) {
  const work = useWork();
  return (
    <>
      {work.error && <ErrorNotice error={work.error} />}
      <div className="jd-job-list">
        {jobs.map((job) => (
          <article className="jd-job-row" key={job.id}>
            <Link
              className="jd-job-identity"
              to={`/jobs/${job.id}${goalId ? `?goal=${goalId}` : ""}`}
            >
              <span
                className="jd-company-mark"
                style={{ background: "#466b9d" }}
              >
                {job.company.slice(0, 1)}
              </span>
              <span>
                <strong>{job.title}</strong>
                <small>
                  {job.company} · {job.city || "地点待确认"} ·{" "}
                  {job.recruitment_type || "类型待确认"}
                </small>
              </span>
            </Link>
            <div className="jd-job-match">
              <span className="jd-status">
                {resultNames[job.assessment?.status || ""] || job.status}
              </span>
              <small>
                {job.assessment?.pending.slice(0, 2).join("、") ||
                  "查看来源依据"}
              </small>
            </div>
            {goalId && (
              <button
                className="jd-save"
                aria-label={`想投${job.company}`}
                disabled={work.busy}
                onClick={() =>
                  void work.perform(() =>
                    command(
                      `/jobs/${job.id}/decision`,
                      {
                        goal_id: goalId,
                        decision:
                          job.decision?.value === "want" ? "undecided" : "want",
                      },
                      "PUT",
                    ),
                  )
                }
              >
                <Icon
                  name={job.decision?.value === "want" ? "check" : "plus"}
                  size={15}
                />
              </button>
            )}
          </article>
        ))}
      </div>
    </>
  );
}

export function Today({ goals, goalId }: GoalContext) {
  const work = useWork();
  const workspace = useQuery({
    queryKey: ["workspace"],
    queryFn: () =>
      api<{
        actions: Action[];
        inbox: Inbox[];
        runs: Run[];
        subscriptions: Subscription[];
        counts: { jobs: number; applications: number; goals: number };
      }>("/workspace"),
    refetchInterval: 10000,
  });
  const jobs = useQuery({
    queryKey: ["jobs", goalId, "today"],
    queryFn: () => api<Page<Job>>(`/jobs?goal_id=${goalId}&limit=3`),
    enabled: !!goalId,
  });
  const goal = goals.find((goal) => goal.id === goalId);
  const data = workspace.data;
  if (workspace.error)
    return (
      <ErrorNotice
        error={workspace.error}
        retry={() => void workspace.refetch()}
      />
    );
  return (
    <>
      <Heading
        title="今天的求职安排"
        description={`${data?.actions.length || 0} 项待办，${data?.inbox.length || 0} 条新提醒`}
      >
        <Link className="jd-button" to="/assistant">
          <Icon name="spark" />
          和助手聊聊
        </Link>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <div className="jd-today-layout">
        <div>
          <section className="jd-focus">
            <div className="jd-focus-header">
              <span>
                <span className="jd-live-dot" />
                今日焦点
              </span>
              <Link to="/applications">全部申请</Link>
            </div>
            <div className="jd-focus-body">
              <div className="jd-focus-icon">
                <Icon name="file" size={26} />
              </div>
              <div>
                <h2>{data?.actions[0]?.title || "从求职目标开始找机会"}</h2>
                <p>
                  {data?.actions[0]?.due_at
                    ? dateTime(data.actions[0].due_at)
                    : goal
                      ? `${goal.name} · 继续发现和核验岗位`
                      : "先告诉助手你想找什么岗位"}
                </p>
              </div>
            </div>
            <div className="jd-focus-footer">
              <span>已保存 {data?.counts.applications || 0} 条申请</span>
              <Link
                className="jd-button"
                to={
                  data?.actions[0]?.application_id
                    ? `/applications/${data.actions[0].application_id}`
                    : "/assistant"
                }
              >
                继续处理
                <Icon name="arrow" size={15} />
              </Link>
            </div>
          </section>
          <section className="jd-section jd-opportunities-section">
            <div className="jd-section-title">
              <h2>当前目标下的机会</h2>
              <Link to="/opportunities">全部机会 →</Link>
            </div>
            {jobs.error ? (
              <ErrorNotice
                error={jobs.error}
                retry={() => void jobs.refetch()}
              />
            ) : jobs.data?.items.length ? (
              <JobRows jobs={jobs.data.items} goalId={goalId} />
            ) : (
              <Empty title="还没有可判断的岗位">
                <Link to="/assistant">说明求职意向，开始查找</Link>
              </Empty>
            )}
          </section>
          {data?.inbox.map((item) => (
            <article className="v2-notice" key={item.id}>
              <strong>{item.title}</strong>
              <p>{item.body}</p>
              {item.job_id && (
                <Link to={`/jobs/${item.job_id}`}>查看岗位 →</Link>
              )}
            </article>
          ))}
        </div>
        <aside>
          <section className="jd-goal-panel">
            <div className="jd-section-title">
              <h3>当前求职目标</h3>
              <Link to="/goals">编辑</Link>
            </div>
            <div className="jd-goal-symbol">
              <Icon name="applications" size={23} />
            </div>
            <h2>{goal?.name || "尚未建立"}</h2>
            <div className="jd-goal-facts">
              <span>
                招聘类型<strong>{goal?.recruitment_type || "待补充"}</strong>
              </span>
              <span>
                地域偏好
                <strong>
                  {goal?.preferences.cities?.join("、") || "不限"}
                </strong>
              </span>
              <span>
                历史岗位<strong>{data?.counts.jobs || 0}</strong>
              </span>
            </div>
            <Link className="jd-outline-button jd-full" to="/subscriptions">
              管理目标与订阅
            </Link>
          </section>
          <section className="jd-schedule-panel">
            <h3>接下来的安排</h3>
            <div className="jd-agenda">
              {data?.actions.slice(0, 6).map((action) => (
                <div className="jd-agenda-line" key={action.id}>
                  <span className="jd-agenda-dot" />
                  <small>
                    {action.due_at ? dateTime(action.due_at) : "时间待确认"}
                  </small>
                  <strong>{action.title}</strong>
                  <div className="v2-actions">
                    {action.application_id && (
                      <Link to={`/applications/${action.application_id}`}>
                        查看申请
                      </Link>
                    )}
                    <button
                      onClick={() =>
                        void work.perform(() =>
                          command(
                            `/actions/${action.id}`,
                            {
                              expected_revision: action.revision,
                              completed: true,
                            },
                            "PATCH",
                          ),
                        )
                      }
                    >
                      完成
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <Link className="jd-text-button" to="/runs">
            运行与接管记录 →
          </Link>
        </aside>
      </div>
      {data?.runs
        .filter((run) => run.status === "running" || run.status === "queued")
        .map((run) => (
          <RunNotice key={run.id} runId={run.id} />
        ))}
    </>
  );
}

export function Opportunities({ goals, goalId, setGoalId }: GoalContext) {
  const [search, setSearch] = useSearchParams();
  const query = search.get("query") || "";
  const filter = search.get("filter") || "";
  const offset = Number(search.get("offset")) || 0;
  const [runId, setRunId] = useState<number | null>(null);
  const [url, setUrl] = useState("");
  const work = useWork();
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["jobs", goalId, query, filter, offset],
    queryFn: () =>
      api<Page<Job>>(
        `/jobs?goal_id=${goalId}&query=${encodeURIComponent(query)}&status=${filter}&offset=${offset}`,
      ),
    enabled: !!goalId,
    placeholderData: (previous) => previous,
  });
  const change = (key: string, value: string) =>
    setSearch((previous) => {
      previous.set(key, value);
      previous.delete("offset");
      return previous;
    });
  const discover = async (urls: string[] = []) => {
    if (!goalId) return;
    const result = await work.perform(() =>
      command<Run>("/discoveries", {
        operation_id: operationId(),
        goal_id: goalId,
        urls,
        mode: urls.length ? "import" : "search",
      }),
    );
    if (result) setRunId(result.id);
  };
  useEffect(() => {
    if (list.data?.items.length && goalId)
      void command("/result-exposures", {
        goal_id: goalId,
        job_ids: list.data.items.map((job) => job.id),
      }).catch(() => undefined);
  }, [list.data, goalId]);
  return (
    <>
      <Heading
        title="机会清单"
        description="对照资格、来源和当前求职条件，比较值得申请的岗位"
      >
        <button
          className="jd-button"
          disabled={work.busy || !goalId}
          onClick={() => void discover()}
        >
          <Icon name="opportunities" />
          联网找新机会
        </button>
      </Heading>
      <GoalSelect
        goals={goals}
        value={goalId}
        onChange={(id) => {
          setGoalId(id);
          setSearch({});
        }}
      />
      {work.error && <ErrorNotice error={work.error} />}
      <form
        className="v2-inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          void discover([url]);
        }}
      >
        <input
          type="url"
          aria-label="导入岗位链接"
          placeholder="粘贴岗位详情链接"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
        <button className="jd-outline-button" disabled={work.busy || !goalId}>
          读取并导入
        </button>
      </form>
      {runId && (
        <RunNotice
          runId={runId}
          onFinished={() =>
            void client.invalidateQueries({ queryKey: ["jobs"] })
          }
        />
      )}
      <div className="jd-filter-bar">
        <div className="jd-tabs">
          {[
            ["", "全部机会"],
            ["pass", "资格符合"],
            ["unknown", "待确认"],
            ["fail", "不符合"],
            ["want", "想投"],
            ["later", "暂缓"],
            ["rejected", "不感兴趣"],
            ["closed", "已关闭"],
          ].map(([value, label]) => (
            <button
              className={filter === value ? "active" : ""}
              key={value}
              onClick={() => change("filter", value)}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          aria-label="搜索岗位"
          placeholder="搜索公司、岗位、城市"
          value={query}
          onChange={(event) => change("query", event.target.value)}
        />
      </div>
      {list.error && (
        <ErrorNotice error={list.error} retry={() => void list.refetch()} />
      )}
      <section className="jd-section">
        <div className="jd-section-title">
          <h3>{list.data?.total || 0} 个已保存岗位</h3>
          <span className="jd-subtle">硬条件、方向与偏好排序</span>
        </div>
        {list.isPending ? (
          <p role="status">正在读取岗位与资格…</p>
        ) : list.data?.items.length ? (
          <JobRows jobs={list.data.items} goalId={goalId} />
        ) : (
          <Empty title={goalId ? "当前范围没有岗位" : "先建立一个求职目标"}>
            <Link to="/goals">调整目标或条件</Link>
          </Empty>
        )}
        <div className="v2-pagination">
          <button
            disabled={!offset}
            onClick={() =>
              setSearch((previous) => {
                previous.set("offset", String(Math.max(0, offset - 30)));
                return previous;
              })
            }
          >
            上一页
          </button>
          <span>第 {Math.floor(offset / 30) + 1} 页</span>
          <button
            disabled={list.data?.next_offset == null}
            onClick={() =>
              setSearch((previous) => {
                previous.set("offset", String(list.data!.next_offset));
                return previous;
              })
            }
          >
            下一页
          </button>
        </div>
      </section>
    </>
  );
}

export function JobDetail({ goalId }: GoalContext) {
  const { jobId } = useParams();
  const work = useWork();
  const navigate = useNavigate();
  const [resumeId, setResumeId] = useState(0);
  const [runId, setRunId] = useState<number | null>(null);
  const query = useQuery({
    queryKey: ["job", jobId, goalId],
    queryFn: () =>
      api<Job>(`/jobs/${jobId}${goalId ? `?goal_id=${goalId}` : ""}`),
  });
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: () => api<Resume[]>("/resumes"),
  });
  const job = query.data;
  if (query.error)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!job) return <p role="status">正在读取岗位…</p>;
  const start = async () => {
    const result = await work.perform(() =>
      command<Application>("/applications", {
        operation_id: operationId(),
        job_id: job.id,
        company: job.company,
        title: job.title,
        city: job.city,
        url: job.url,
      }),
    );
    if (result) navigate(`/applications/${result.id}`);
  };
  return (
    <>
      <Heading
        title={job.title}
        description={`${job.company} · ${job.city || "地点待确认"} · ${job.recruitment_type || "类型待确认"}`}
      >
        <a
          className="jd-outline-button"
          href={job.url}
          target="_blank"
          rel="noreferrer"
        >
          打开申请入口 ↗
        </a>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <div className="v2-detail-layout">
        <div>
          <section className="jd-section">
            <h2>推荐依据与个人优势</h2>
            <div className="v2-long-text">
              {job.assessment?.reasons.join("、") || "方向相关性仍需核对"}
              {job.assessment?.strengths?.map((strength) => (
                <p key={strength.keyword}>
                  已确认经历涉及 {strength.keyword} · 事实 #{strength.fact_id}
                </p>
              ))}
            </div>
            <h2>逐项资格与依据</h2>
            <div className="v2-facts-grid">
              <span>
                岗位状态
                <strong>
                  {job.status === "open"
                    ? "最近核验开放"
                    : job.status === "closed"
                      ? "已关闭"
                      : "待重新核验"}
                </strong>
              </span>
              <span>
                最近核验<strong>{dateTime(job.verified_at)}</strong>
              </span>
              <span>
                发布时间<strong>{job.published_at || "未知"}</strong>
              </span>
              <span>
                刷新时间<strong>{job.refreshed_at || "未知"}</strong>
              </span>
              <span>
                首次发现<strong>{dateTime(job.created_at)}</strong>
              </span>
              <span>
                明确截止<strong>{job.deadline_at || "未知"}</strong>
              </span>
            </div>
            {job.assessment?.checks.map((check) => (
              <div className="v2-qualification" key={check.key}>
                <strong>{check.label}</strong>
                <div>
                  <span>岗位要求 · {valueText(check.requirement)}</span>
                  <span>个人条件 · {valueText(check.candidate)}</span>
                  <small>{check.reason}</small>
                </div>
                <span className={`v2-result ${check.result}`}>
                  {resultNames[check.result]}
                </span>
              </div>
            ))}
            <div className="v2-actions">
              <Link to="/profile">补充个人条件</Link>
            </div>
          </section>
          <section className="jd-section v2-spaced">
            <h2>原始招聘内容</h2>
            <div className="v2-long-text">{job.description}</div>
          </section>
          <section className="jd-section v2-spaced">
            <h2>来源证据</h2>
            {job.sources?.map((source) => (
              <details key={source.id}>
                <summary>
                  {source.source.name} · {valueText(source.source.kind)} ·{" "}
                  {valueText(source.source.status)}
                </summary>
                <a href={source.url} target="_blank" rel="noreferrer">
                  原始链接 ↗
                </a>
                {source.evidence.map((evidence) => (
                  <div key={evidence.id}>
                    <small>{dateTime(evidence.created_at)}</small>
                    <DetailsList
                      data={
                        evidence.fields.requirements || {
                          graduation_text: evidence.fields.graduation_text,
                        }
                      }
                    />
                    <p className="v2-long-text">{evidence.text}</p>
                  </div>
                ))}
              </details>
            ))}
            {Object.keys(job.program).length > 0 && (
              <details>
                <summary>公司招聘项目及适用范围</summary>
                <DetailsList data={job.program} />
              </details>
            )}
          </section>
        </div>
        <aside>
          <section className="jd-goal-panel">
            <h3>我的决定</h3>
            <div className="v2-actions">
              {[
                ["want", "想投"],
                ["later", "暂缓"],
                ["rejected", "不感兴趣"],
                ["undecided", "恢复未决定"],
              ].map(([decision, label]) => (
                <button
                  className={
                    job.decision?.value === decision
                      ? "jd-button"
                      : "jd-outline-button"
                  }
                  key={decision}
                  disabled={work.busy || !goalId}
                  onClick={() =>
                    void work.perform(() =>
                      command(
                        `/jobs/${job.id}/decision`,
                        { goal_id: goalId, decision },
                        "PUT",
                      ),
                    )
                  }
                >
                  {label}
                </button>
              ))}
            </div>
            <h3>准备材料</h3>
            <select
              aria-label="选择基础简历"
              value={
                resumeId ||
                resumes.data?.find((resume) => resume.active)?.id ||
                ""
              }
              onChange={(event) => setResumeId(Number(event.target.value))}
            >
              <option value="">选择简历</option>
              {resumes.data?.map((resume) => (
                <option key={resume.id} value={resume.id}>
                  {resume.name}
                </option>
              ))}
            </select>
            <div className="v2-actions">
              <button
                className="jd-button"
                disabled={work.busy}
                onClick={() =>
                  void work.perform(async () => {
                    const id =
                      resumeId ||
                      resumes.data?.find((resume) => resume.active)?.id;
                    if (!id) throw new Error("先导入或选择基础简历");
                    const run = await command<Run>(
                      `/jobs/${job.id}/materials`,
                      { operation_id: operationId(), resume_id: id },
                    );
                    setRunId(run.id);
                    return run;
                  })
                }
              >
                生成修改建议
              </button>
              <Link to="/profile">管理简历</Link>
            </div>
            <form
              className="v2-spaced"
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                void work.perform(async () => {
                  const result = await api<{ material_id: number }>(
                    `/jobs/${job.id}/materials/import`,
                    { method: "POST", body: data },
                  );
                  navigate(`/materials/${result.material_id}`);
                  return result;
                });
              }}
            >
              <label>
                上传自行准备的岗位材料
                <input
                  name="file"
                  type="file"
                  accept=".pdf,.docx,.md,.txt"
                  required
                />
              </label>
              <button className="jd-outline-button" disabled={work.busy}>
                保存材料版本
              </button>
            </form>
            <button
              className="jd-outline-button jd-full"
              onClick={() => void start()}
              disabled={work.busy}
            >
              建立申请记录
            </button>
            {job.applications?.map((application) => (
              <Link
                className="v2-record-link"
                key={application.id}
                to={`/applications/${application.id}`}
              >
                {application.stage} · 已有关联申请 →
              </Link>
            ))}
            {job.materials?.map((material) => (
              <Link
                className="v2-record-link"
                key={material.id}
                to={`/materials/${material.id}`}
              >
                材料 #{material.id} · {material.status} →
              </Link>
            ))}
          </section>
        </aside>
      </div>
      {runId && (
        <RunNotice
          runId={runId}
          onFinished={(run) => {
            if (run.result.material_id)
              navigate(`/materials/${run.result.material_id}`);
          }}
        />
      )}
    </>
  );
}

export function Assistant({ goals, goalId, setGoalId }: GoalContext) {
  const { threadId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const work = useWork();
  const [input, setInput] = useState("");
  const [runId, setRunId] = useState<number | null>(null);
  const [newGoal, setNewGoal] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const threads = useQuery({
    queryKey: ["threads"],
    queryFn: () => api<Thread[]>("/threads"),
  });
  const thread = useQuery({
    queryKey: ["thread", threadId],
    queryFn: () => api<Thread>(`/threads/${threadId}`),
    enabled: !!threadId,
    refetchInterval: (query) =>
      runId ||
      query.state.data?.runs?.some((run) =>
        ["queued", "running"].includes(run.status),
      )
        ? 700
        : false,
  });
  useEffect(() => setRunId(null), [threadId]);
  useEffect(() => {
    if (
      thread.data?.active_goal_id &&
      goals.some((goal) => goal.id === thread.data!.active_goal_id)
    )
      setGoalId(thread.data.active_goal_id);
  }, [thread.data?.active_goal_id]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [thread.data?.messages?.at(-1)?.content]);
  const send = async () => {
    if (!input.trim()) return;
    const result = await work.perform(async () => {
      let id = threadId;
      if (!id) {
        const created = await command<Thread>("/threads", {
          goal_id: goalId,
          title: input.slice(0, 24),
        });
        id = String(created.id);
        navigate(`/assistant/${id}`, { replace: true });
      }
      const run = await command<Run>(`/threads/${id}/messages`, {
        operation_id: operationId(),
        content: input,
        goal_id: goalId,
      });
      setInput("");
      return run;
    });
    if (result) setRunId(result.id);
  };
  return (
    <>
      <Heading
        title="求职助手"
        description="说明意向、修改条件，或直接推进一项申请"
      >
        <Link className="jd-outline-button" to="/assistant">
          新对话
        </Link>
        {threadId && (
          <button
            className="jd-outline-button"
            disabled={work.busy}
            onClick={() => {
              if (
                window.confirm(
                  "删除当前对话内容？已保存的资料、目标与申请记录会保留。",
                )
              ) {
                void work.perform(async () => {
                  const result = await api(`/threads/${threadId}`, {
                    method: "DELETE",
                  });
                  setRunId(null);
                  navigate("/assistant");
                  return result;
                });
              }
            }}
          >
            删除当前对话
          </button>
        )}
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <div className="v2-assistant-layout">
        <aside className="v2-thread-list">
          <h3>历史会话</h3>
          {threads.error && <ErrorNotice error={threads.error} />}{" "}
          {threads.data?.map((item) => (
            <Link
              className={String(item.id) === threadId ? "active" : ""}
              key={item.id}
              to={`/assistant/${item.id}`}
            >
              {item.title}
              <small>{dateTime(item.updated_at)}</small>
            </Link>
          ))}
        </aside>
        <section className="jd-chat">
          <GoalSelect
            goals={goals}
            value={goalId}
            onChange={(id) => {
              setGoalId(id);
              if (threadId)
                void work
                  .perform(() =>
                    command(`/threads/${threadId}`, { goal_id: id }, "PATCH"),
                  )
                  .then(() =>
                    client.invalidateQueries({
                      queryKey: ["thread", threadId],
                    }),
                  );
            }}
          />
          {!goals.length && (
            <form
              className="v2-onboarding"
              onSubmit={(event) => {
                event.preventDefault();
                void work.perform(async () => {
                  const goal = await command<Goal>("/goals", {
                    operation_id: operationId(),
                    name: newGoal,
                    direction: newGoal,
                  });
                  setGoalId(goal.id);
                  return goal;
                });
              }}
            >
              <h2>想找什么岗位？</h2>
              <p>先保存一个方向，简历与到岗条件可随后补充。</p>
              <input
                aria-label="求职方向"
                value={newGoal}
                onChange={(event) => setNewGoal(event.target.value)}
                placeholder="例如 AI 产品经理实习"
                required
              />
              <button className="jd-button" disabled={work.busy}>
                建立目标
              </button>
            </form>
          )}
          <div className="jd-chat-scroll">
            {!thread.data?.messages?.length && (
              <div className="jd-chat-message assistant">
                <span className="jd-assistant-mark">
                  <Icon name="spark" />
                </span>
                <div>
                  <strong>求职助手</strong>
                  <p>
                    告诉我你想找的岗位。明确条件会保存到当前目标，你也可以粘贴岗位链接，或让我设置每天检查。
                  </p>
                  <p className="jd-subtle">
                    需要先配置模型，联网发现还需要搜索连接。
                  </p>
                  <Link to="/settings">查看连接状态 →</Link>
                </div>
              </div>
            )}
            {thread.data?.messages?.map((message) => (
              <div
                className={`jd-chat-message ${message.role}`}
                key={message.id}
              >
                {message.role === "assistant" && (
                  <span className="jd-assistant-mark">
                    <Icon name="spark" />
                  </span>
                )}
                <div>
                  <strong>{message.role === "user" ? "你" : "求职助手"}</strong>
                  <p className="v2-long-text">
                    {message.content || "正在处理…"}
                  </p>
                </div>
              </div>
            ))}
            {thread.error && <ErrorNotice error={thread.error} />}
            <div ref={end} />
          </div>
          {Array.from(
            new Set([
              ...(thread.data?.runs?.slice(0, 5).map((run) => run.id) || []),
              ...(runId ? [runId] : []),
            ]),
          ).map((savedRunId) => (
            <RunNotice
              key={savedRunId}
              runId={savedRunId}
              onFinished={() => {
                if (savedRunId === runId) setRunId(null);
                void client.invalidateQueries();
              }}
            />
          ))}
          <form
            className="jd-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <span>
              <span className="jd-goal-dot" />
              {goals.find((goal) => goal.id === goalId)?.name ||
                "当前目标待建立"}
            </span>
            <div>
              <textarea
                aria-label="发送给求职助手"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                rows={2}
                placeholder="补充一个条件，或开始下一项任务…"
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              <button
                className="jd-button"
                disabled={
                  work.busy ||
                  !!runId ||
                  thread.data?.runs?.some(
                    (run) =>
                      run.kind === "conversation" &&
                      ["queued", "running"].includes(run.status),
                  ) ||
                  !input.trim()
                }
                aria-label="发送"
              >
                <Icon name="arrow" />
              </button>
            </div>
            <small>Enter 发送 · Shift + Enter 换行</small>
          </form>
        </section>
      </div>
    </>
  );
}
