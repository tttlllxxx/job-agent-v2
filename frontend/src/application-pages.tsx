import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api, command, dateTime, operationId, localDateTime } from "./api";
import {
  Empty,
  ErrorNotice,
  Heading,
  Icon,
  Modal,
  DetailsList,
  valueText,
} from "./components";
import { useWork } from "./hooks";
import { InterviewNotes } from "./data-tools";
import type {
  Action,
  Application,
  FillSession,
  MaterialVersion,
  Page,
  Progress,
  Resume,
  Snapshot,
} from "./types";

const stages = [
  "准备中",
  "已投递",
  "笔试中",
  "一面",
  "二面",
  "三面",
  "面试中",
  "HR 面",
  "Offer",
  "未通过",
  "主动放弃",
];
const columns = [
  { key: "company", label: "公司", width: 160 },
  { key: "title", label: "岗位名称", width: 230 },
  { key: "stage", label: "申请阶段", width: 135 },
  { key: "city", label: "城市", width: 100 },
  { key: "applied_at", label: "投递日期", width: 150 },
  { key: "next_action", label: "下一步行动", width: 230 },
  { key: "material", label: "申请材料", width: 180 },
  { key: "notes", label: "备注", width: 220 },
] as const;
type Column = (typeof columns)[number]["key"];
const isEnded = (stage: string) =>
  ["Offer", "未通过", "主动放弃", "岗位取消", "已撤回"].includes(stage);
const stageColor = (stage: string) =>
  isEnded(stage)
    ? stage === "Offer"
      ? "green"
      : "red"
    : stage.includes("面")
      ? "purple"
      : stage.includes("笔试") || stage.includes("测评")
        ? "amber"
        : stage === "准备中"
          ? "gray"
          : "blue";

export function Applications() {
  const work = useWork();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const query = params.get("query") || "";
  const offset = Number(params.get("offset")) || 0;
  const view = params.get("view") || "全部申请";
  const sort = params.get("sort") || "default";
  const stage = params.get("stage") || "";
  const filter = (changes: Record<string, string>) => {
    setSelected([]);
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("offset");
      for (const [key, value] of Object.entries(changes)) next.set(key, value);
      return next;
    });
  };
  const paginate = (nextOffset: number) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("offset", String(nextOffset));
      return next;
    });
  const [panel, setPanel] = useState("");
  const [hidden, setHidden] = useState<string[]>([]);
  const [editing, setEditing] = useState<{
    id: number;
    key: Column;
    value: string;
  } | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [adding, setAdding] = useState(false);
  const list = useQuery({
    queryKey: ["applications", query, stage, offset, view, sort],
    queryFn: () =>
      api<Page<Application>>(
        `/applications?query=${encodeURIComponent(query)}&stage=${encodeURIComponent(stage)}&offset=${offset}&limit=100&view=${encodeURIComponent(view)}&sort=${sort}`,
      ),
    placeholderData: (previous) => previous,
  });
  const apps = list.data?.items || [];
  const rows = apps;
  const visible = columns.filter((column) => !hidden.includes(column.key));
  const allSelected =
    !!rows.length && rows.every((row) => selected.includes(row.id));
  const patch = async (app: Application, changes: Partial<Application>) =>
    work.perform(() =>
      command<Application>(
        `/applications/${app.id}`,
        { expected_revision: app.revision, ...changes },
        "PATCH",
      ),
    );
  const commit = async () => {
    if (!editing) return;
    const draft = editing;
    const app = apps.find((app) => app.id === draft.id);
    if (!app) return;
    const result = await patch(app, { [draft.key]: draft.value });
    if (result)
      setEditing((current) =>
        current?.id === draft.id && current.key === draft.key ? null : current,
      );
  };
  return (
    <>
      <Heading
        title="申请台账"
        description="一行一条申请，点击单元格编辑阶段、日期、行动与材料"
      />
      {work.error && <ErrorNotice error={work.error} />}
      <section className="jd-base">
        <div className="jd-base-title">
          <span className="jd-base-symbol">▦</span>
          <div>
            <h2>我的求职记录</h2>
            <p>修改保存到本机，申请详情保留时间线和实际材料</p>
          </div>
          <span className="jd-base-saved">
            <span className="jd-live-dot" />
            已加载 {list.data?.total || 0} 条记录
          </span>
        </div>
        <div className="jd-base-views">
          {["全部申请", "进行中", "面试安排", "已结束"].map((item) => (
            <button
              className={view === item ? "active" : ""}
              key={item}
              onClick={() => {
                filter({ view: item });
              }}
            >
              ▦ {item}
            </button>
          ))}
        </div>
        <div className="jd-base-toolbar">
          <div className="jd-base-tools">
            <button
              onClick={() => setPanel(panel === "fields" ? "" : "fields")}
            >
              ▥ 字段
            </button>
            <button
              onClick={() => setPanel(panel === "filter" ? "" : "filter")}
            >
              ≡ 筛选
            </button>
            <label className="jd-base-sort">
              ⇅
              <select
                aria-label="申请排序"
                value={sort}
                onChange={(event) => filter({ sort: event.target.value })}
              >
                <option value="default">默认排序</option>
                <option value="newest">投递日期从新到旧</option>
                <option value="oldest">投递日期从旧到新</option>
              </select>
            </label>
          </div>
          <div className="jd-base-toolbar-right">
            <label className="jd-base-search">
              ⌕
              <input
                aria-label="搜索申请记录"
                placeholder="搜索公司、岗位"
                value={query}
                onChange={(event) => filter({ query: event.target.value })}
              />
            </label>
            <button className="jd-button" onClick={() => setAdding(true)}>
              ＋ 新增记录
            </button>
          </div>
        </div>
        {panel === "fields" && (
          <fieldset className="jd-base-fields">
            <legend>显示字段</legend>
            {columns
              .filter((column) => column.key !== "company")
              .map((column) => (
                <label key={column.key}>
                  <input
                    type="checkbox"
                    checked={!hidden.includes(column.key)}
                    onChange={(event) =>
                      setHidden((previous) =>
                        event.target.checked
                          ? previous.filter((key) => key !== column.key)
                          : [...previous, column.key],
                      )
                    }
                  />
                  {column.label}
                </label>
              ))}
          </fieldset>
        )}
        {panel === "filter" && (
          <div className="jd-base-filter">
            <label>
              申请阶段
              <select
                value={stage}
                onChange={(event) => {
                  filter({ stage: event.target.value });
                }}
              >
                <option value="">所有阶段</option>
                {Array.from(
                  new Set([...stages, ...apps.map((app) => app.stage)]),
                ).map((stage) => (
                  <option key={stage}>{stage}</option>
                ))}
              </select>
            </label>
            <button onClick={() => filter({ stage: "" })}>清除筛选</button>
          </div>
        )}
        {selected.length > 0 && (
          <div className="jd-base-selection">
            <span>已选择 {selected.length} 条记录</span>
            <label>
              批量设置阶段
              <select
                aria-label="批量设置阶段"
                value=""
                onChange={(event) => {
                  const value = event.target.value;
                  void work.perform(async () => {
                    await command("/applications/bulk-stage", {
                      operation_id: operationId(),
                      stage: value,
                      items: rows
                        .filter((app) => selected.includes(app.id))
                        .map((app) => ({
                          id: app.id,
                          expected_revision: app.revision,
                        })),
                    });
                    setSelected([]);
                    return true;
                  });
                }}
              >
                <option value="">选择阶段</option>
                {stages.map((stage) => (
                  <option key={stage}>{stage}</option>
                ))}
              </select>
            </label>
            <button onClick={() => setSelected([])}>取消选择</button>
          </div>
        )}
        {list.error && (
          <ErrorNotice error={list.error} retry={() => void list.refetch()} />
        )}
        <div
          className="jd-base-scroll"
          tabIndex={0}
          role="region"
          aria-label="申请表格，可左右滚动"
        >
          <table className="jd-base-table">
            <caption className="sr-only">申请记录表格</caption>
            <colgroup>
              <col style={{ width: 48 }} />
              {visible.map((column) => (
                <col key={column.key} style={{ width: column.width }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th className="jd-base-row-number">
                  <input
                    type="checkbox"
                    aria-label="选择本页全部申请"
                    checked={allSelected}
                    onChange={(event) =>
                      setSelected(
                        event.target.checked ? rows.map((row) => row.id) : [],
                      )
                    }
                  />
                </th>
                {visible.map((column) => (
                  <th
                    scope="col"
                    key={column.key}
                    className={
                      column.key === "company" ? "jd-base-company" : ""
                    }
                  >
                    <span className="jd-base-field-type">
                      {column.key === "stage"
                        ? "◉"
                        : column.key === "applied_at"
                          ? "▦"
                          : "Aa"}
                    </span>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr
                  key={row.id}
                  className={selected.includes(row.id) ? "is-selected" : ""}
                >
                  <td className="jd-base-row-number">
                    <span>{offset + index + 1}</span>
                    <input
                      type="checkbox"
                      aria-label={`选择${row.company}`}
                      checked={selected.includes(row.id)}
                      onChange={(event) =>
                        setSelected((old) =>
                          event.target.checked
                            ? [...old, row.id]
                            : old.filter((id) => id !== row.id),
                        )
                      }
                    />
                  </td>
                  {visible.map((column) => (
                    <td
                      key={column.key}
                      className={
                        column.key === "company" ? "jd-base-company" : ""
                      }
                    >
                      {column.key === "stage" ? (
                        <select
                          aria-label={`${row.company}申请阶段`}
                          className={`jd-base-stage ${stageColor(row.stage)}`}
                          value={row.stage}
                          disabled={work.busy}
                          onChange={(event) =>
                            void patch(row, { stage: event.target.value })
                          }
                        >
                          {Array.from(new Set([...stages, row.stage])).map(
                            (stage) => (
                              <option key={stage}>{stage}</option>
                            ),
                          )}
                        </select>
                      ) : editing?.id === row.id &&
                        editing.key === column.key ? (
                        <input
                          autoFocus
                          aria-label={`编辑${row.company}的${column.label}`}
                          type={column.key === "applied_at" ? "date" : "text"}
                          value={editing.value}
                          onChange={(event) =>
                            setEditing({
                              ...editing,
                              value: event.target.value,
                            })
                          }
                          onBlur={() => void commit()}
                          onKeyDown={(event) => {
                            if (event.key === "Enter")
                              event.currentTarget.blur();
                            if (event.key === "Escape") setEditing(null);
                          }}
                        />
                      ) : (
                        <div className="v2-table-cell-wrap">
                          <button
                            className={`jd-base-cell ${!row[column.key] ? "is-empty" : ""}`}
                            aria-label={`编辑${row.company}的${column.label}`}
                            title={row[column.key]}
                            onClick={() =>
                              setEditing({
                                id: row.id,
                                key: column.key,
                                value: row[column.key],
                              })
                            }
                          >
                            {row[column.key] || "—"}
                          </button>
                          {column.key === "company" && (
                            <Link
                              aria-label={`查看${row.company}申请详情`}
                              className="v2-open-record"
                              to={`/applications/${row.id}`}
                            >
                              ↗
                            </Link>
                          )}
                        </div>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && (
            <Empty
              title={list.isPending ? "正在读取申请…" : "当前范围没有申请"}
            />
          )}
          <button className="jd-base-add-row" onClick={() => setAdding(true)}>
            ＋ 添加一条申请记录
          </button>
          <div className="jd-base-grid-space" />
        </div>
        <div className="jd-base-footer">
          <span>
            {rows.length} 条已加载记录 · 共 {list.data?.total || 0} 条
          </span>
          <div>
            <button
              disabled={!offset}
              onClick={() => paginate(Math.max(0, offset - 100))}
            >
              上一页
            </button>
            <button
              disabled={list.data?.next_offset == null}
              onClick={() => paginate(list.data!.next_offset!)}
            >
              下一页
            </button>
          </div>
          <span>Enter 保存 · Esc 取消 · 左右滚动查看字段</span>
        </div>
      </section>
      {adding && (
        <Modal title="记录外部申请" close={() => setAdding(false)}>
          <form
            className="jd-modal-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void work.perform(async () => {
                const result = await command<Application>("/applications", {
                  operation_id: operationId(),
                  company: data.get("company"),
                  title: data.get("title"),
                  city: data.get("city"),
                  applied_at: data.get("applied_at"),
                  url: data.get("url"),
                  stage: data.get("applied_at") ? "已投递" : "准备中",
                });
                setAdding(false);
                setParams({});
                return result;
              });
            }}
          >
            <label>
              公司
              <input name="company" required maxLength={255} />
            </label>
            <label>
              岗位
              <input name="title" required maxLength={300} />
            </label>
            <label>
              城市
              <input name="city" />
            </label>
            <label>
              申请链接
              <input name="url" type="url" />
            </label>
            <label>
              实际投递日期
              <input name="applied_at" type="date" />
            </label>
            <button className="jd-button" disabled={work.busy}>
              保存申请
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

export function ApplicationDetail() {
  const { applicationId } = useParams();
  const work = useWork();
  const [editingEvent, setEditingEvent] = useState<Progress | null>(null);
  const [addingEvent, setAddingEvent] = useState(false);
  const [submission, setSubmission] = useState(false);
  const query = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => api<Application>(`/applications/${applicationId}`),
  });
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: () => api<Resume[]>("/resumes"),
  });
  const versions = useQuery({
    queryKey: ["material-versions", query.data?.job_id],
    queryFn: () =>
      api<MaterialVersion[]>(
        `/material-versions${query.data?.job_id ? `?job_id=${query.data.job_id}` : ""}`,
      ),
    enabled: !!query.data,
  });
  const app = query.data;
  if (query.error)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!app) return <p role="status">正在读取申请…</p>;
  return (
    <>
      <Heading
        title={`${app.company} · ${app.title}`}
        description={`${app.stage} · ${app.city || "地点待补充"}`}
      >
        <div className="v2-actions">
          <Link
            className="jd-outline-button"
            to={`/applications/${app.id}/fill`}
          >
            辅助填写
          </Link>
          <button className="jd-button" onClick={() => setSubmission(true)}>
            登记官网提交结果
          </button>
        </div>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <div className="v2-detail-layout">
        <section className="jd-section">
          <div className="jd-section-title">
            <h2>进展时间线</h2>
            <button
              className="jd-text-button"
              onClick={() => {
                setEditingEvent(null);
                setAddingEvent(true);
              }}
            >
              ＋ 添加进展
            </button>
          </div>
          {!app.events?.length && <Empty title="暂时没有进展事件" />}
          <div className="v2-timeline">
            {app.events?.map((event) => (
              <article key={event.id}>
                <div className={`v2-timeline-dot ${event.state}`} />
                <small>
                  {event.state === "planned"
                    ? "已预约"
                    : event.state === "completed"
                      ? "已完成"
                      : event.state === "cancelled"
                        ? "已取消"
                        : "已跳过"}{" "}
                  · {dateTime(event.occurred_at || event.planned_at)}
                </small>
                <h3>{event.label}</h3>
                {Boolean(event.data.note) && <p>{String(event.data.note)}</p>}
                <button
                  className="jd-text-button"
                  onClick={() => {
                    setEditingEvent(event);
                    setAddingEvent(true);
                  }}
                >
                  修改或纠正日期
                </button>
                {event.state === "planned" && (
                  <button
                    className="jd-text-button"
                    onClick={() =>
                      void work.perform(() =>
                        command(`/connections/calendar/${event.id}`),
                      )
                    }
                  >
                    写入求职日历
                  </button>
                )}
                {Array.isArray(event.data.revisions) && (
                  <details>
                    <summary>
                      修订历史 · {event.data.revisions.length} 次
                    </summary>
                    {event.data.revisions.map((revision, index) => (
                      <DetailsList key={index} data={revision} />
                    ))}
                  </details>
                )}
              </article>
            ))}
          </div>
          <h2>下一步行动</h2>
          {app.actions?.map((action) => (
            <div className="v2-record-row" key={action.id}>
              <label>
                <input
                  type="checkbox"
                  checked={action.completed}
                  onChange={(event) =>
                    void work.perform(() =>
                      command(
                        `/actions/${action.id}`,
                        {
                          expected_revision: action.revision,
                          completed: event.target.checked,
                        },
                        "PATCH",
                      ),
                    )
                  }
                />
                {action.title}
              </label>
              <small>{dateTime(action.due_at)}</small>
            </div>
          ))}
          <form
            className="v2-inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              void work.perform(async () => {
                const result = await command("/actions", {
                  title: data.get("title"),
                  application_id: app.id,
                  due_at: data.get("due_at")
                    ? new Date(String(data.get("due_at"))).toISOString()
                    : null,
                });
                form.reset();
                return result;
              });
            }}
          >
            <input
              name="title"
              aria-label="下一步行动"
              placeholder="要做什么"
              required
            />
            <input
              name="due_at"
              aria-label="行动截止时间"
              type="datetime-local"
            />
            <button className="jd-outline-button" disabled={work.busy}>
              添加行动
            </button>
          </form>
        </section>
        <aside>
          <section className="jd-goal-panel">
            <h3>申请信息</h3>
            <div className="jd-detail-facts">
              <span>
                实际投递<strong>{app.applied_at || "未登记"}</strong>
              </span>
              <span>
                材料<strong>{app.material || "待核对"}</strong>
              </span>
              <span>
                当前阶段<strong>{app.stage}</strong>
              </span>
            </div>
            {app.url && (
              <a
                className="jd-outline-button jd-full"
                href={app.url}
                target="_blank"
                rel="noreferrer"
              >
                打开官网申请 ↗
              </a>
            )}
            {app.job_id && (
              <Link className="v2-record-link" to={`/jobs/${app.job_id}`}>
                关联岗位与 JD →
              </Link>
            )}
            <h3>实际提交的材料</h3>
            {!!app.extra?.linked_resume_ids?.length && (
              <div className="v2-spaced">
                <p className="jd-subtle">
                  历史关联简历，请核对是否为实际投递版本。
                </p>
                {app.extra.linked_resume_ids.map((id) => (
                  <Link
                    key={id}
                    className="v2-record-link"
                    to={`/profile?resume=${id}`}
                  >
                    {resumes.data?.find((resume) => resume.id === id)?.name ||
                      `简历记录 #${id}`}{" "}
                    →
                  </Link>
                ))}
              </div>
            )}
            {Object.keys(app.submitted_materials).length ? (
              <DetailsList data={app.submitted_materials} />
            ) : (
              <p className="jd-subtle">
                尚未登记，可在确认官网提交结果时补充。
              </p>
            )}
            <p className="jd-subtle">{app.notes || "暂无备注"}</p>
            <h3>填写会话</h3>
            {app.fill_sessions?.map((session) => (
              <Link
                className="v2-record-link"
                key={session.id}
                to={`/applications/${app.id}/fill?session=${session.id}`}
              >
                会话 #{session.id} · {session.status} →
              </Link>
            ))}
          </section>
        </aside>
      </div>
      <InterviewNotes application={app} />
      {addingEvent && (
        <Modal
          title={editingEvent ? "修改进展事件" : "添加进展或预约"}
          close={() => setAddingEvent(false)}
        >
          <form
            key={editingEvent?.id || "new"}
            className="jd-modal-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const state = String(data.get("state"));
              const time = data.get("time")
                ? new Date(String(data.get("time"))).toISOString()
                : null;
              const patch = {
                label: data.get("label"),
                state,
                occurred_at: state === "completed" ? time : null,
                planned_at: state === "planned" ? time : null,
                data: { ...editingEvent?.data, note: data.get("note") },
              };
              void work.perform(async () => {
                const result = editingEvent
                  ? await command(
                      `/applications/${app.id}/events/${editingEvent.id}`,
                      { ...patch, expected_revision: editingEvent.revision },
                      "PATCH",
                    )
                  : await command(`/applications/${app.id}/events`, {
                      ...patch,
                      operation_id: operationId(),
                    });
                setAddingEvent(false);
                return result;
              });
            }}
          >
            <label>
              阶段名称
              <input
                name="label"
                defaultValue={editingEvent?.label || ""}
                required
                placeholder="例如 二面、加面、笔试"
              />
            </label>
            <label>
              事件状态
              <select
                name="state"
                defaultValue={editingEvent?.state || "planned"}
              >
                <option value="planned">未来预约</option>
                <option value="completed">已完成</option>
                <option value="cancelled">已取消</option>
                <option value="skipped">已跳过</option>
              </select>
            </label>
            <label>
              时间
              <input
                name="time"
                type="datetime-local"
                defaultValue={localDateTime(
                  editingEvent?.occurred_at || editingEvent?.planned_at,
                )}
              />
            </label>
            <label>
              备注
              <textarea
                name="note"
                defaultValue={String(editingEvent?.data.note || "")}
              />
            </label>
            <button className="jd-button" disabled={work.busy}>
              保存事件
            </button>
          </form>
        </Modal>
      )}
      {submission && (
        <Modal title="确认官网提交结果" close={() => setSubmission(false)}>
          <form
            className="jd-modal-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void work.perform(async () => {
                const result = await command(
                  `/applications/${app.id}/submission-confirmations`,
                  {
                    operation_id: operationId(),
                    applied_at: data.get("date"),
                    materials: {
                      resume_ids: data.get("resume")
                        ? [Number(data.get("resume"))]
                        : [],
                      description: data.get("material"),
                      version_ids: data.get("version")
                        ? [Number(data.get("version"))]
                        : [],
                    },
                    note: data.get("note"),
                  },
                );
                setSubmission(false);
                return result;
              });
            }}
          >
            <p>确认你已在官网完成该岗位提交，并记录实际使用的材料。</p>
            <label>
              实际投递日期
              <input
                name="date"
                type="date"
                required
                defaultValue={app.applied_at}
              />
            </label>
            <label>
              基础简历
              <select name="resume">
                <option value="">自行上传的其他材料</option>
                {resumes.data?.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              岗位材料版本
              <select name="version">
                <option value="">未使用岗位生成版本</option>
                {versions.data?.map((version) => (
                  <option key={version.id} value={version.id}>
                    固定版本 #{version.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              材料文件名与版本
              <input name="material" required defaultValue={app.material} />
            </label>
            <label>
              核对说明
              <textarea name="note" />
            </label>
            <button className="jd-button" disabled={work.busy}>
              确认已在官网提交成功
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

export function FillWorkspace() {
  const { applicationId } = useParams();
  const [params, setParams] = useSearchParams();
  const sessionId = Number(params.get("session")) || 0;
  const work = useWork();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [sensitive, setSensitive] = useState<string[]>([]);
  const [overwrite, setOverwrite] = useState<string[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const application = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => api<Application>(`/applications/${applicationId}`),
  });
  const session = useQuery({
    queryKey: ["fill", sessionId],
    queryFn: () => api<FillSession>(`/fill-sessions/${sessionId}`),
    enabled: !!sessionId,
    refetchInterval: 3000,
  });
  const scan = async () => {
    await work.perform(async () => {
      const snapshot = await command<Snapshot>(
        `/fill-sessions/${sessionId}/scan`,
      );
      setSelected(
        snapshot.preview
          .filter((field) => field.state === "ready")
          .map((field) => field.key),
      );
      return snapshot;
    });
  };
  return (
    <>
      <Heading
        title="辅助填写"
        description={`${application.data?.company || ""} · ${application.data?.title || ""}`}
      >
        <Link
          className="jd-outline-button"
          to={`/applications/${applicationId}`}
        >
          返回申请
        </Link>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}
      <section className="jd-section">
        <h2>选择执行入口</h2>
        <p className="jd-subtle">
          当前页扩展用于日常网申。可见浏览器支持扫描与填写，上传和最终提交在官网由你完成。
        </p>
        <form
          className="v2-inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            void work.perform(async () => {
              const result = await command<FillSession>(
                `/applications/${applicationId}/fill-sessions`,
                {
                  operation_id: operationId(),
                  url: data.get("url"),
                  executor: data.get("executor"),
                },
              );
              setParams({ session: String(result.id) });
              return result;
            });
          }}
        >
          <input
            type="url"
            name="url"
            aria-label="申请页面链接"
            required
            defaultValue={application.data?.url}
            placeholder="https://…"
          />
          <select name="executor" aria-label="填写入口">
            <option value="extension">当前页 Chrome 扩展</option>
            <option value="playwright">可见浏览器</option>
          </select>
          <button className="jd-button" disabled={work.busy}>
            开始或继续
          </button>
        </form>
      </section>
      {session.data && (
        <>
          <section className="jd-section v2-spaced">
            <div className="jd-section-title">
              <h2>
                会话 #{sessionId} · {session.data.status}
              </h2>
              <button
                className="jd-outline-button"
                onClick={() =>
                  void work.perform(() =>
                    command(`/fill-sessions/${sessionId}/pause`),
                  )
                }
              >
                暂存，稍后继续
              </button>
            </div>
            {session.data.executor === "playwright" ? (
              <button
                className="jd-button"
                onClick={() => void scan()}
                disabled={work.busy}
              >
                打开并扫描当前页面
              </button>
            ) : (
              <p className="v2-notice">
                请在 Chrome 加载项目 browser-extension
                目录。打开网申页面后，在扩展侧栏选择申请 #{applicationId}
                ，再扫描当前页。工作台会显示最新预览与填写结果。
              </p>
            )}
            {session.data.status === "needs_scan" && (
              <p className="v2-notice">
                当前页面需要重新扫描，核对后才能继续填写。
              </p>
            )}
            {session.data.snapshot?.blockers.map((blocker) => (
              <div className="v2-error" key={blocker}>
                需要接管 · {blocker}
              </div>
            ))}
            {session.data.snapshot && (
              <>
                <p className="jd-subtle">
                  当前页 · {session.data.snapshot.url}
                </p>
                <div className="v2-fill-fields">
                  {session.data.snapshot.preview.map((field) => (
                    <div className="v2-fill-field" key={field.key}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selected.includes(field.key)}
                          disabled={
                            (field.has_value &&
                              !overwrite.includes(field.key)) ||
                            (field.sensitive && !sensitive.includes(field.key))
                          }
                          onChange={(event) =>
                            setSelected((old) =>
                              event.target.checked
                                ? [...old, field.key]
                                : old.filter((key) => key !== field.key),
                            )
                          }
                        />
                        <strong>{field.label}</strong>
                        {field.required && <small>必填</small>}
                      </label>
                      <span>
                        {field.state === "existing"
                          ? "页面已有值"
                          : field.state === "ready"
                            ? "拟填写"
                            : field.state === "sensitive"
                              ? "需单独授权"
                              : "缺少答案"}{" "}
                        · {field.source || "需要补充"}
                      </span>
                      <input
                        aria-label={`${field.label}答案`}
                        value={answers[field.key] ?? field.proposed ?? ""}
                        onChange={(event) =>
                          setAnswers((old) => ({
                            ...old,
                            [field.key]: event.target.value,
                          }))
                        }
                      />
                      {field.has_value && (
                        <label>
                          <input
                            type="checkbox"
                            checked={overwrite.includes(field.key)}
                            onChange={(event) =>
                              setOverwrite((old) =>
                                event.target.checked
                                  ? [...old, field.key]
                                  : old.filter((key) => key !== field.key),
                              )
                            }
                          />
                          允许覆盖已有值
                        </label>
                      )}
                      {field.sensitive && (
                        <label>
                          <input
                            type="checkbox"
                            checked={sensitive.includes(field.key)}
                            onChange={(event) =>
                              setSensitive((old) =>
                                event.target.checked
                                  ? [...old, field.key]
                                  : old.filter((key) => key !== field.key),
                              )
                            }
                          />
                          授权填写该敏感字段
                        </label>
                      )}
                    </div>
                  ))}
                </div>
                {session.data.executor === "playwright" && (
                  <button
                    className="jd-button"
                    disabled={
                      work.busy ||
                      !selected.length ||
                      session.data.status === "needs_scan"
                    }
                    onClick={() =>
                      void work.perform(() =>
                        command(`/fill-sessions/${sessionId}/execute`, {
                          operation_id: operationId(),
                          snapshot_id: session.data!.snapshot!.id,
                          selected,
                          sensitive,
                          overwrite,
                          answers,
                        }),
                      )
                    }
                  >
                    确认填写所选 {selected.length} 项
                  </button>
                )}
              </>
            )}
          </section>
          <section className="jd-section v2-spaced">
            <h2>已扫描与填写的页面</h2>
            {session.data.pages.map((page, index) => (
              <details key={index}>
                <summary>
                  {String(page.url || "当前页")} ·{" "}
                  {page.status === "filled"
                    ? "已填写"
                    : page.status === "scanned"
                      ? "已扫描"
                      : valueText(page.status)}
                </summary>
                <p className="jd-subtle">{dateTime(String(page.at || ""))}</p>
                {Array.isArray(page.results) && (
                  <p>
                    {
                      page.results.filter(
                        (item: { verified?: boolean }) => item.verified,
                      ).length
                    }{" "}
                    项已回读验证，共 {page.results.length}{" "}
                    项。请核对网页后继续。
                  </p>
                )}
              </details>
            ))}
          </section>
        </>
      )}
    </>
  );
}
