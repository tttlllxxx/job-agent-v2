import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, command, dateTime, operationId } from "./api";
import {
  Empty,
  ErrorNotice,
  GoalSelect,
  Heading,
  Modal,
  RunNotice,
  DetailsList,
  valueText,
} from "./components";
import { useWork } from "./hooks";
import { MailConnections, RestoreData, UsageRecords } from "./data-tools";
import type { Company, Goal, Inbox, Run, Source, Subscription } from "./types";
import type { GoalContext } from "./discovery-pages";

export function Goals({
  goals,
  goalId,
  setGoalId,
  companiesOnly = false,
}: GoalContext & { companiesOnly?: boolean }) {
  const work = useWork();
  const [editing, setEditing] = useState<Goal | "new" | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const companies = useQuery({
    queryKey: ["companies"],
    queryFn: () => api<Company[]>("/companies"),
  });
  const selected = goals.find((goal) => goal.id === goalId);
  return (
    <>
      <Heading
        title={companiesOnly ? "关注公司" : "求职目标"}
        description="个人事实与目标条件分别管理，多目标各自保存条件与订阅"
      >
        <button className="jd-button" onClick={() => setEditing("new")}>
          ＋ 新目标
        </button>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <GoalSelect goals={goals} value={goalId} onChange={setGoalId} />
      {!companiesOnly && (
        <div className="v2-goals-grid">
          {goals.map((goal) => (
            <section
              className={`jd-section ${goalId === goal.id ? "v2-selected" : ""}`}
              key={goal.id}
            >
              <div className="jd-section-title">
                <h2>{goal.name}</h2>
                <button
                  className="jd-text-button"
                  onClick={() => setEditing(goal)}
                >
                  编辑
                </button>
              </div>
              <div className="jd-detail-facts">
                <span>
                  方向<strong>{goal.direction}</strong>
                </span>
                <span>
                  招聘类型<strong>{goal.recruitment_type || "不限"}</strong>
                </span>
                <span>
                  地域偏好
                  <strong>
                    {goal.preferences.cities?.join("、") || "不限"}
                  </strong>
                </span>
                <span>
                  地域硬条件
                  <strong>
                    {Array.isArray(goal.constraints.cities)
                      ? goal.constraints.cities.join("、")
                      : "不限"}
                  </strong>
                </span>
              </div>
              <div className="v2-actions">
                <button
                  className="jd-outline-button"
                  onClick={() => setGoalId(goal.id)}
                >
                  {goalId === goal.id ? "当前目标" : "切换目标"}
                </button>
                <Link to="/subscriptions">管理订阅</Link>
                <button
                  className="jd-text-button"
                  onClick={() =>
                    void work.perform(() =>
                      command(
                        `/goals/${goal.id}`,
                        { expected_revision: goal.revision, archived: true },
                        "PATCH",
                      ),
                    )
                  }
                >
                  归档
                </button>
              </div>
            </section>
          ))}
        </div>
      )}
      <section className="jd-section v2-spaced">
        <div className="jd-section-title">
          <h2>{selected?.name || "当前目标"} · 公司范围</h2>
          <button
            className="jd-outline-button"
            disabled={!goalId || work.busy}
            onClick={() =>
              void work.perform(async () => {
                const run = await command<Run>("/discoveries", {
                  operation_id: operationId(),
                  goal_id: goalId,
                  mode: "companies",
                  urls: [],
                });
                setRunId(run.id);
                return run;
              })
            }
          >
            发现中小公司
          </button>
        </div>
        {companies.error && <ErrorNotice error={companies.error} />}
        <div className="v2-company-list">
          {companies.data?.map((company) => (
            <article key={company.id}>
              <div>
                <strong>{company.name}</strong>
                <small>{String(company.data.size || "规模待核实")}</small>
                <p>{String(company.data.reason || "来自已保存招聘信息")}</p>
                <div className="v2-source-links">
                  {company.sources.map((source) => (
                    <a
                      key={source.id}
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {source.name} · {source.status} ↗
                    </a>
                  ))}
                </div>
              </div>
              <label>
                <input
                  type="checkbox"
                  checked={company.goals.some(
                    (goal) => goal.goal_id === goalId && goal.active,
                  )}
                  disabled={!goalId || work.busy}
                  onChange={(event) =>
                    void work.perform(() =>
                      command(`/goals/${goalId}/companies`, {
                        company_id: company.id,
                        active: event.target.checked,
                      }),
                    )
                  }
                />
                关注
              </label>
            </article>
          ))}
        </div>
      </section>
      {runId && <RunNotice runId={runId} />}{" "}
      {editing && (
        <Modal
          title={editing === "new" ? "建立求职目标" : "编辑求职目标"}
          close={() => setEditing(null)}
        >
          <form
            className="jd-modal-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const cities = String(data.get("cities") || "")
                .split(/[、,，\s]+/)
                .filter(Boolean);
              const hard = data.get("hard") === "on";
              const payload = {
                name: data.get("name"),
                direction: data.get("direction"),
                recruitment_type: data.get("type"),
                preferences: {
                  ...(editing !== "new" ? editing.preferences : {}),
                  cities: hard ? [] : cities,
                },
                constraints: {
                  ...(editing !== "new" ? editing.constraints : {}),
                  cities: hard ? cities : [],
                },
              };
              void work.perform(async () => {
                const result =
                  editing === "new"
                    ? await command<Goal>("/goals", {
                        ...payload,
                        operation_id: operationId(),
                      })
                    : await command<Goal>(
                        `/goals/${editing.id}`,
                        { ...payload, expected_revision: editing.revision },
                        "PATCH",
                      );
                setGoalId(result.id);
                setEditing(null);
                return result;
              });
            }}
          >
            <label>
              目标名称
              <input
                name="name"
                required
                defaultValue={editing !== "new" ? editing.name : ""}
              />
            </label>
            <label>
              岗位方向
              <input
                name="direction"
                required
                defaultValue={editing !== "new" ? editing.direction : ""}
              />
            </label>
            <label>
              招聘类型
              <select
                name="type"
                defaultValue={editing !== "new" ? editing.recruitment_type : ""}
              >
                <option value="">待补充或不限</option>
                <option>日常实习</option>
                <option>暑期实习</option>
                <option>应届招聘</option>
                <option>社会招聘</option>
              </select>
            </label>
            <label>
              城市或省份
              <input
                name="cities"
                placeholder="江苏、浙江、上海"
                defaultValue={
                  editing !== "new"
                    ? (Array.isArray(editing.constraints.cities) &&
                      editing.constraints.cities.length
                        ? editing.constraints.cities
                        : editing.preferences.cities || []
                      ).join("、")
                    : ""
                }
              />
            </label>
            <label className="jd-checkbox">
              <input
                type="checkbox"
                name="hard"
                defaultChecked={
                  editing !== "new" &&
                  Array.isArray(editing.constraints.cities) &&
                  editing.constraints.cities.length > 0
                }
              />
              只看这些地区，作为硬条件
            </label>
            <button className="jd-button" disabled={work.busy}>
              保存并生效
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

export function Subscriptions({ goals, goalId, setGoalId }: GoalContext) {
  const work = useWork();
  const navigate = useNavigate();
  const [create, setCreate] = useState(false);
  const list = useQuery({
    queryKey: ["subscriptions"],
    queryFn: () => api<Subscription[]>("/subscriptions"),
  });
  return (
    <>
      <Heading
        title="目标订阅"
        description="按当前条件检查岗位。无变化时保持安静，本地服务运行期间执行。"
      >
        <button
          className="jd-button"
          disabled={!goalId}
          onClick={() => setCreate(true)}
        >
          ＋ 新订阅
        </button>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <GoalSelect goals={goals} value={goalId} onChange={setGoalId} />
      {list.error && <ErrorNotice error={list.error} />}
      <div className="v2-goals-grid">
        {list.data?.map((subscription) => (
          <section className="jd-section" key={subscription.id}>
            <div className="jd-section-title">
              <h2>{subscription.name}</h2>
              <span className="jd-status">
                {subscription.enabled ? "监控中" : "已暂停"}
              </span>
            </div>
            <p className="jd-subtle">
              {goals.find((goal) => goal.id === subscription.goal_id)?.name ||
                "历史目标"}
            </p>
            <div className="jd-detail-facts">
              <span>
                执行约定
                <strong>
                  {subscription.config.kind === "interval"
                    ? `每 ${subscription.config.interval_minutes} 分钟`
                    : `每天 ${subscription.config.time || "09:00"}`}
                </strong>
              </span>
              <span>
                时区
                <strong>
                  {subscription.config.timezone || "Asia/Shanghai"}
                </strong>
              </span>
              <span>
                下次执行<strong>{dateTime(subscription.next_run_at)}</strong>
              </span>
              <span>
                上次成功
                <strong>{dateTime(subscription.last_success_at)}</strong>
              </span>
            </div>
            <div className="v2-actions">
              <Link
                className="jd-outline-button"
                to={`/subscriptions/${subscription.id}`}
              >
                详情与检查记录
              </Link>
              <button
                onClick={() =>
                  void work.perform(() =>
                    command(
                      `/subscriptions/${subscription.id}`,
                      {
                        expected_revision: subscription.revision,
                        enabled: !subscription.enabled,
                      },
                      "PATCH",
                    ),
                  )
                }
              >
                {subscription.enabled ? "暂停" : "恢复"}
              </button>
            </div>
          </section>
        ))}
      </div>
      {!list.data?.length && (
        <Empty title={goalId ? "当前目标还没有订阅" : "先选择一个求职目标"} />
      )}
      {create && (
        <Modal title="创建每日订阅" close={() => setCreate(false)}>
          <SubscriptionForm
            busy={work.busy}
            onSave={(config) =>
              void work.perform(async () => {
                const result = await command<Subscription>("/subscriptions", {
                  operation_id: operationId(),
                  goal_id: goalId,
                  config,
                });
                setCreate(false);
                navigate(`/subscriptions/${result.id}`);
                return result;
              })
            }
          />
        </Modal>
      )}
    </>
  );
}

function SubscriptionForm({
  subscription,
  busy,
  onSave,
}: {
  subscription?: Subscription;
  busy: boolean;
  onSave: (config: Subscription["config"]) => void;
}) {
  const [scope, setScope] = useState(
    subscription?.config.scope_mode === "selected" ? "selected" : "all",
  );
  const companies = useQuery({
    queryKey: ["companies"],
    queryFn: () => api<Company[]>("/companies"),
  });
  return (
    <form
      className="jd-modal-form"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onSave({
          ...subscription?.config,
          kind: "daily",
          time: String(data.get("time")),
          timezone: String(data.get("timezone")),
          include_unknown: data.get("unknown") === "on",
          scope_mode: scope,
          company_ids:
            scope === "selected" ? data.getAll("company_ids").map(Number) : [],
          follow_applied: data.get("follow_applied") === "on",
          events: [
            "new_match",
            ...["deadline_due", "reopened", "qualification_changed"].filter(
              (kind) => data.get(kind) === "on",
            ),
          ],
          channels: [
            "inbox",
            ...(data.get("feishu") === "on" ? ["feishu"] : []),
          ],
        });
      }}
    >
      <label>
        关注范围
        <select
          value={scope}
          onChange={(event) => setScope(event.target.value)}
        >
          <option value="all">目标关注的全部公司</option>
          <option value="selected">指定公司</option>
        </select>
      </label>
      {scope === "selected" && (
        <fieldset>
          <legend>选择公司</legend>
          {companies.data?.map((company) => (
            <label className="jd-checkbox" key={company.id}>
              <input
                type="checkbox"
                name="company_ids"
                value={company.id}
                defaultChecked={subscription?.config.company_ids?.includes(
                  company.id,
                )}
              />
              {company.name}
            </label>
          ))}
        </fieldset>
      )}
      <label>
        每日检查时间
        <input
          type="time"
          name="time"
          defaultValue={subscription?.config.time || "09:00"}
          required
        />
      </label>
      <label>
        时区
        <input
          name="timezone"
          defaultValue={subscription?.config.timezone || "Asia/Shanghai"}
          required
        />
      </label>
      <label className="jd-checkbox">
        <input
          type="checkbox"
          name="unknown"
          defaultChecked={subscription?.config.include_unknown !== false}
        />
        包含资格待确认的相关岗位
      </label>
      <label className="jd-checkbox">
        <input
          type="checkbox"
          name="follow_applied"
          defaultChecked={Boolean(subscription?.config.follow_applied)}
        />
        对已投递岗位保留所选变化跟进
      </label>
      <fieldset>
        <legend>附加事件</legend>
        {[
          ["deadline_due", "明确截止日期"],
          ["reopened", "重新开放"],
          ["qualification_changed", "资格条件变化"],
        ].map(([kind, label]) => (
          <label className="jd-checkbox" key={kind}>
            <input
              type="checkbox"
              name={kind}
              defaultChecked={subscription?.config.events?.includes(kind)}
            />
            {label}
          </label>
        ))}
      </fieldset>
      <label className="jd-checkbox">
        <input
          type="checkbox"
          name="feishu"
          defaultChecked={subscription?.config.channels?.includes("feishu")}
        />
        同时发送到已配置飞书渠道
      </label>
      <p className="jd-subtle">
        首次检查结果作为基线。修改条件后先展示新范围结果，再持续提醒。
      </p>
      <button className="jd-button" disabled={busy}>
        保存订阅
      </button>
    </form>
  );
}

export function SubscriptionDetail() {
  const { subscriptionId } = useParams();
  const work = useWork();
  const [editing, setEditing] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const query = useQuery({
    queryKey: ["subscription", subscriptionId],
    queryFn: () =>
      api<{
        subscription: Subscription;
        checks: {
          id: number;
          run_id: number;
          status: string;
          created_at: string;
          coverage: Record<string, unknown>;
        }[];
      }>(`/subscriptions/${subscriptionId}/history`),
    refetchInterval: 10000,
  });
  const subscription = query.data?.subscription;
  if (query.error) return <ErrorNotice error={query.error} />;
  if (!subscription) return <p role="status">正在读取订阅…</p>;
  return (
    <>
      <Heading
        title={subscription.name}
        description="配置、覆盖范围、运行结果与下一次执行均可查"
      >
        <div className="v2-actions">
          <button
            className="jd-outline-button"
            onClick={() => setEditing(true)}
          >
            编辑约定
          </button>
          <button
            className="jd-button"
            disabled={work.busy}
            onClick={() =>
              void work.perform(async () => {
                const run = await command<Run>(
                  `/subscriptions/${subscription.id}/checks`,
                  { operation_id: operationId() },
                );
                setRunId(run.id);
                return run;
              })
            }
          >
            立即检查
          </button>
        </div>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <section className="jd-section">
        <div className="v2-facts-grid">
          <span>
            状态<strong>{subscription.enabled ? "启用" : "暂停"}</strong>
          </span>
          <span>
            下次执行<strong>{dateTime(subscription.next_run_at)}</strong>
          </span>
          <span>
            上次检查<strong>{dateTime(subscription.last_checked_at)}</strong>
          </span>
          <span>
            上次成功<strong>{dateTime(subscription.last_success_at)}</strong>
          </span>
          <span>
            基线
            <strong>
              {subscription.initialized ? "已建立" : "首轮核验中"}
            </strong>
          </span>
          <span>
            通知渠道
            <strong>
              {(subscription.config.channels || ["inbox"])
                .map((channel) => (channel === "feishu" ? "飞书" : "站内通知"))
                .join("、")}
            </strong>
          </span>
        </div>
        <details>
          <summary>完整生效配置</summary>
          <p>
            {subscription.config.kind === "interval"
              ? `每 ${subscription.config.interval_minutes} 分钟`
              : `每天 ${subscription.config.time || "09:00"}`}{" "}
            · {subscription.config.timezone || "Asia/Shanghai"}
          </p>
          <p>
            公司范围：
            {subscription.config.scope_mode === "selected"
              ? `已选 ${subscription.config.company_ids?.length || 0} 家公司`
              : "当前目标下全部关注公司"}
          </p>
          <p>
            提醒事件：
            {(subscription.config.events || ["new_match"])
              .map(
                (event) =>
                  ({
                    new_match: "新匹配岗位",
                    deadline_due: "明确截止临近",
                    reopened: "岗位重新开放",
                    qualification_changed: "资格要求变化",
                  })[event] || event,
              )
              .join("、")}
          </p>
          <p>
            {subscription.config.include_unknown === false
              ? "只提醒资格全部确认符合的岗位"
              : "保留资格待确认的相关岗位"}{" "}
            ·{" "}
            {subscription.config.follow_applied
              ? "跟进已投递岗位的已选事件"
              : "已投递岗位停止机会提醒"}
          </p>
        </details>
        <Link to="/inbox">通知及发送状态 →</Link>
      </section>
      {runId && <RunNotice runId={runId} />}
      <section className="jd-section v2-spaced">
        <h2>检查历史</h2>
        {query.data?.checks.map((check) => (
          <details key={check.id}>
            <summary>
              {dateTime(check.created_at)} · {valueText(check.status)} · 运行 #
              {check.run_id}
            </summary>
            <RunNotice runId={check.run_id} />
            <DetailsList
              data={{
                coverage: check.coverage.coverage || [],
                job_ids: check.coverage.job_ids || [],
              }}
            />
          </details>
        ))}
      </section>
      {editing && (
        <Modal title="修改订阅" close={() => setEditing(false)}>
          <SubscriptionForm
            subscription={subscription}
            busy={work.busy}
            onSave={(config) =>
              void work.perform(async () => {
                const result = await command(
                  `/subscriptions/${subscription.id}`,
                  { expected_revision: subscription.revision, config },
                  "PATCH",
                );
                setEditing(false);
                return result;
              })
            }
          />
        </Modal>
      )}
    </>
  );
}

export function InboxPage() {
  const work = useWork();
  const query = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api<Inbox[]>("/inbox"),
    refetchInterval: 10000,
  });
  return (
    <>
      <Heading
        title="通知记录"
        description="站内结果、外部发送状态和已读状态分别记录"
      />
      {work.error && <ErrorNotice error={work.error} />}{" "}
      {query.error && <ErrorNotice error={query.error} />}
      <section className="jd-section">
        {query.data?.map((item) => (
          <article className="v2-notice" key={item.id}>
            <div className="jd-section-title">
              <h2>{item.title}</h2>
              <small>
                {item.seen_at ? "已读" : "未读"} · {dateTime(item.created_at)}
              </small>
            </div>
            <p>{item.body}</p>
            <div className="v2-actions">
              {item.job_id && <Link to={`/jobs/${item.job_id}`}>查看岗位</Link>}
              {!item.seen_at && (
                <button
                  onClick={() =>
                    void work.perform(() =>
                      command(`/inbox/${item.id}`, {}, "PATCH"),
                    )
                  }
                >
                  标记已读
                </button>
              )}
            </div>
            {item.deliveries.map((delivery) => (
              <div key={delivery.id} className="v2-record-row">
                <span>
                  {delivery.channel} · {delivery.status}
                </span>
                <small>{delivery.error}</small>
                {["failed", "unknown"].includes(delivery.status) && (
                  <button
                    onClick={() =>
                      void work.perform(() =>
                        command(`/deliveries/${delivery.id}/retry`),
                      )
                    }
                  >
                    核对后重试发送
                  </button>
                )}
              </div>
            ))}
          </article>
        ))}
        {!query.data?.length && <Empty title="当前没有变化提醒" />}
      </section>
    </>
  );
}

export function RunsPage() {
  const query = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
    refetchInterval: 5000,
  });
  return (
    <>
      <Heading
        title="运行记录"
        description="执行过程、错误、已完成结果与恢复入口"
      />
      {query.error && <ErrorNotice error={query.error} />}
      <div className="v2-run-list">
        {query.data?.map((run) => (
          <div key={run.id}>
            <h3>
              {run.kind} · #{run.id}
            </h3>
            <RunNotice runId={run.id} />
          </div>
        ))}
      </div>
    </>
  );
}

export function SourcesPage() {
  const work = useWork();
  const query = useQuery({
    queryKey: ["sources"],
    queryFn: () => api<Source[]>("/sources"),
  });
  return (
    <>
      <Heading
        title="来源健康"
        description="失败与受限来源保留最近成功时间，历史岗位保留原核验日期"
      />
      {work.error && <ErrorNotice error={work.error} />}
      <form
        className="v2-inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          void work.perform(async () => {
            const result = await command("/sources", {
              name: data.get("name"),
              url: data.get("url"),
            });
            form.reset();
            return result;
          });
        }}
      >
        <input name="name" placeholder="来源名称" required />
        <input name="url" type="url" placeholder="招聘入口链接" required />
        <button className="jd-button" disabled={work.busy}>
          添加来源
        </button>
      </form>
      {query.error && <ErrorNotice error={query.error} />}
      <section className="jd-section">
        {query.data?.map((source) => (
          <article className="v2-record-row" key={source.id}>
            <div>
              <a href={source.url} target="_blank" rel="noreferrer">
                {source.name} ↗
              </a>
              <small>
                {source.kind} · {source.status}
              </small>
              <p>{source.error}</p>
            </div>
            <div>
              <small>最近检查 · {dateTime(source.last_checked_at)}</small>
              <small>最近成功 · {dateTime(source.last_success_at)}</small>
            </div>
          </article>
        ))}
      </section>
    </>
  );
}

export function SettingsPage() {
  const work = useWork();
  const [check, setCheck] = useState("");
  const [backupUrl, setBackupUrl] = useState("");
  const query = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<Record<string, unknown>>("/settings"),
  });
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () =>
      api<{
        model_ready: boolean;
        search_ready: boolean;
        migration: Record<string, unknown>;
      }>("/status"),
  });
  return (
    <>
      <Heading
        title="设置与连接"
        description="模型、搜索、提醒渠道与数据备份"
      />
      {work.error && <ErrorNotice error={work.error} />}
      <div className="v2-settings-links">
        <Link to="/sources">来源健康 →</Link>
        <Link to="/subscriptions">自动检查 →</Link>
        <Link to="/inbox">通知记录 →</Link>
        <Link to="/runs">运行与恢复 →</Link>
      </div>
      {query.error && <ErrorNotice error={query.error} />}
      <section className="jd-section">
        <h2>模型与搜索连接</h2>
        <p className="jd-subtle">
          模型用于对话、岗位提取和材料建议，搜索服务仅接收岗位意向。简历事实进入模型前由你确认。
        </p>
        <p>
          模型 {status.data?.model_ready ? "已配置" : "待配置"} · 搜索{" "}
          {status.data?.search_ready ? "已配置" : "待配置"}
        </p>
        {query.data && (
          <form
            key={JSON.stringify(query.data)}
            className="v2-settings-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const values: Record<string, unknown> = {
                llm_provider: data.get("llm_provider"),
                llm_base_url: data.get("llm_base_url"),
                llm_model: data.get("llm_model"),
              };
              for (const key of [
                "llm_api_key",
                "search_api_key",
                "feishu_webhook",
              ]) {
                if (data.get(key)) values[key] = data.get(key);
              }
              void work.perform(() =>
                command("/settings", { values }, "PATCH"),
              );
            }}
          >
            <label>
              模型连接方式
              <select
                name="llm_provider"
                defaultValue={String(query.data.llm_provider || "api")}
              >
                <option value="api">OpenAI-compatible API</option>
                <option value="codex">pi openai-codex</option>
              </select>
            </label>
            <label>
              Base URL
              <input
                name="llm_base_url"
                type="url"
                defaultValue={String(query.data.llm_base_url || "")}
              />
            </label>
            <label>
              模型名称
              <input
                name="llm_model"
                defaultValue={String(query.data.llm_model || "")}
              />
            </label>
            <label>
              模型 API Key
              <input
                name="llm_api_key"
                type="password"
                autoComplete="new-password"
                placeholder={
                  (query.data.llm_api_key as { configured: boolean })
                    ?.configured
                    ? "已保存，输入可替换"
                    : "填写 API Key"
                }
              />
            </label>
            <label>
              Tavily 搜索 API Key
              <input
                name="search_api_key"
                type="password"
                autoComplete="new-password"
                placeholder={
                  (query.data.search_api_key as { configured: boolean })
                    ?.configured
                    ? "已保存"
                    : "填写搜索 Key"
                }
              />
            </label>
            <label>
              飞书机器人 Webhook
              <input
                name="feishu_webhook"
                type="password"
                placeholder={
                  (query.data.feishu_webhook as { configured: boolean })
                    ?.configured
                    ? "已保存"
                    : "按需配置外部提醒"
                }
              />
            </label>
            <div className="v2-actions">
              <button className="jd-button" disabled={work.busy}>
                保存配置
              </button>
              <button
                type="button"
                className="jd-outline-button"
                disabled={work.busy}
                onClick={() =>
                  void work.perform(async () => {
                    const result = await command<{ ready: boolean }>(
                      "/settings/check-model",
                    );
                    setCheck(result.ready ? "模型连接可用" : "模型响应不正确");
                    return result;
                  })
                }
              >
                检测模型连接
              </button>
            </div>
            {check && <p role="status">{check}</p>}
          </form>
        )}
      </section>
      {query.data && <MailConnections config={query.data} />}
      <section className="jd-section v2-spaced">
        <h2>数据备份与迁移</h2>
        <p className="jd-subtle">
          备份包含本地数据库、原始文件与固定材料版本。文件含个人资料及连接配置，请保存在你信任的位置。
        </p>
        <button
          className="jd-outline-button"
          disabled={work.busy}
          onClick={() =>
            void work.perform(async () => {
              const result = await command<{ url: string }>("/backups");
              setBackupUrl(result.url);
              return result;
            })
          }
        >
          创建完整备份
        </button>
        {backupUrl && (
          <a className="v2-record-link" href={backupUrl}>
            下载刚创建的备份 →
          </a>
        )}
        <details>
          <summary>查看实际迁移报告</summary>
          {status.data?.migration ? (
            <DetailsList
              data={{
                岗位: status.data.migration.jobs,
                申请: status.data.migration.applications,
                简历: status.data.migration.resumes,
                缺失文件: status.data.migration.files_missing,
                迁移时间: status.data.migration.finished_at,
              }}
            />
          ) : (
            <p>这是新建的工作台，尚无历史数据迁移。</p>
          )}
        </details>
        <RestoreData />
        <UsageRecords />
      </section>
    </>
  );
}
