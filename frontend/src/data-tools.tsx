import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, command } from "./api";
import { ErrorNotice, Modal, DetailsList } from "./components";
import { useWork } from "./hooks";
import type { Action, Application, Progress } from "./types";

export function Attachments() {
  const work = useWork();
  const query = useQuery({
    queryKey: ["attachments"],
    queryFn: () =>
      api<{ id: number; name: string; kind: string }[]>("/attachments"),
  });
  return (
    <section className="jd-section v2-spaced">
      <h2>附件与自备文件</h2>
      {Boolean(work.error) && <ErrorNotice error={work.error} />}
      <form
        className="v2-upload"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          void work.perform(async () => {
            const result = await api("/attachments", {
              method: "POST",
              body: data,
            });
            form.reset();
            return result;
          });
        }}
      >
        <label>
          上传作品集、证明或其他申请附件
          <input type="file" name="file" required />
        </label>
        <button className="jd-outline-button" disabled={work.busy}>
          保存附件
        </button>
      </form>
      {query.data?.map((file) => (
        <a
          className="v2-record-link"
          key={file.id}
          href={`/api/attachments/${file.id}/file`}
        >
          {file.name} ↗
        </a>
      ))}
    </section>
  );
}

export function UsageRecords() {
  const query = useQuery({
    queryKey: ["usage"],
    queryFn: () =>
      api<
        {
          id: number;
          model: string;
          purpose: string;
          input_tokens: number;
          output_tokens: number;
          estimated_rmb: number | null;
        }[]
      >("/usage"),
  });
  return (
    <details>
      <summary>模型调用与费用记录</summary>
      {query.error && <ErrorNotice error={query.error} />}{" "}
      {query.data?.map((row) => (
        <div className="v2-record-row" key={row.id}>
          <span>
            {row.model} · {row.purpose}
          </span>
          <small>
            输入 {row.input_tokens} · 输出 {row.output_tokens} ·{" "}
            {row.estimated_rmb == null
              ? "费用未配置"
              : `约 ¥${row.estimated_rmb.toFixed(4)}`}
          </small>
        </div>
      ))}
    </details>
  );
}

export function RestoreData() {
  const work = useWork();
  const [message, setMessage] = useState("");
  return (
    <div className="v2-spaced">
      {Boolean(work.error) && <ErrorNotice error={work.error} />}
      <form
        className="v2-upload"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void work.perform(async () => {
            const result = await api<{ message: string }>("/backups/restore", {
              method: "POST",
              body: data,
            });
            setMessage(result.message);
            return result;
          });
        }}
      >
        <label>
          恢复已下载的工作台备份
          <input type="file" name="file" accept=".zip" required />
        </label>
        <button className="jd-outline-button" disabled={work.busy}>
          校验并准备恢复
        </button>
      </form>
      {message && (
        <p className="v2-notice" role="status">
          {message}
        </p>
      )}
    </div>
  );
}

export function MailConnections({
  config,
}: {
  config: Record<string, unknown>;
}) {
  const work = useWork();
  const [message, setMessage] = useState("");
  const [mail, setMail] = useState<{
    id: number;
    data: Record<string, unknown>;
  } | null>(null);
  const messages = useQuery({
    queryKey: ["mail-records"],
    queryFn: () =>
      api<{ id: number; data: Record<string, unknown> }[]>(
        "/legacy/external_mail_events",
      ),
  });
  const schedules = useQuery({
    queryKey: ["legacy-schedules"],
    queryFn: () =>
      api<{ id: number; data: Record<string, unknown> }[]>(
        "/legacy/automation_schedules",
      ),
  });
  const applications = useQuery({
    queryKey: ["applications", "mail-selection"],
    queryFn: () => api<{ items: Application[] }>("/applications?limit=500"),
  });
  return (
    <section className="jd-section v2-spaced">
      <h2>邮件与日历连接</h2>
      <p className="jd-subtle">
        macOS
        本地运行时，读取招聘邮件并由你确认关联。日历按已确认预约写入系统日历。
      </p>
      {!!schedules.data?.length && (
        <details>
          <summary>迁移前的自动化约定 · {schedules.data.length} 条</summary>
          {schedules.data.map((row) => (
            <p key={row.id}>
              {String(row.data.name || "历史自动化")} · 每{" "}
              {String(row.data.interval_minutes || "—")} 分钟 · 原状态
              {row.data.enabled ? "启用" : "暂停"}
              。原配置已归档，邮件与日历按当前连接设置执行。
            </p>
          ))}
        </details>
      )}
      {Boolean(work.error) && <ErrorNotice error={work.error} />}
      <div className="v2-actions">
        {[
          ["mail_enabled", "启用邮件读取"],
          ["calendar_enabled", "启用日历同步"],
        ].map(([key, label]) => (
          <label className="jd-checkbox" key={key}>
            <input
              type="checkbox"
              checked={Boolean(config[key])}
              disabled={work.busy}
              onChange={(event) =>
                void work.perform(() =>
                  command(
                    "/settings",
                    { values: { [key]: event.target.checked } },
                    "PATCH",
                  ),
                )
              }
            />
            {label}
          </label>
        ))}
      </div>
      <button
        className="jd-outline-button"
        disabled={work.busy || !config.mail_enabled}
        onClick={() =>
          void work.perform(async () => {
            const result = await command<{ added: number[] }>(
              "/connections/mail/sync",
            );
            setMessage(`已读取，新增 ${result.added.length} 条待核对招聘邮件`);
            return result;
          })
        }
      >
        读取最近招聘邮件
      </button>
      {message && <p role="status">{message}</p>}
      {messages.data?.map((record) => (
        <article className="v2-record-row" key={record.id}>
          <div>
            <strong>{String(record.data.subject || "历史邮件")}</strong>
            <small>{String(record.data.status || "待核对")}</small>
          </div>
          <button className="jd-text-button" onClick={() => setMail(record)}>
            核对与关联
          </button>
        </article>
      ))}
      {mail && (
        <Modal title="核对招聘邮件" close={() => setMail(null)}>
          <div className="v2-long-text">
            {String(mail.data.body || mail.data.redacted_summary || "")}
          </div>
          <form
            className="jd-modal-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void work.perform(async () => {
                const result = await command(
                  `/connections/mail/${mail.id}/confirm`,
                  {
                    application_id: Number(data.get("application")),
                    label: data.get("label"),
                    state: data.get("state"),
                    planned_at: data.get("time")
                      ? new Date(String(data.get("time"))).toISOString()
                      : null,
                  },
                );
                setMail(null);
                return result;
              });
            }}
          >
            <label>
              关联申请
              <select name="application" required>
                {applications.data?.items.map((app) => (
                  <option key={app.id} value={app.id}>
                    {app.company} · {app.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              确认阶段
              <input name="label" required placeholder="例如 一面" />
            </label>
            <label>
              状态
              <select name="state">
                <option value="planned">未来预约</option>
                <option value="completed">已完成</option>
              </select>
            </label>
            <label>
              安排时间
              <input type="datetime-local" name="time" />
            </label>
            <button className="jd-button" disabled={work.busy}>
              确认并更新申请
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}

export function InterviewNotes({ application }: { application: Application }) {
  const work = useWork();
  const packs = (application.actions || []).filter(
    (action) =>
      action.data?.kind === "interview_pack" ||
      action.data?.kind === "reflection",
  );
  return (
    <section className="jd-section v2-spaced">
      <h2>面试准备与复盘</h2>
      {Boolean(work.error) && <ErrorNotice error={work.error} />}
      <button
        className="jd-outline-button"
        disabled={work.busy}
        onClick={() =>
          void work.perform(() =>
            command(`/applications/${application.id}/interview-pack`),
          )
        }
      >
        根据关联 JD 与实际材料准备
      </button>
      {packs.map((pack) => (
        <details key={pack.id}>
          <summary>{pack.title}</summary>
          {pack.data?.kind === "reflection" ? (
            <p className="v2-long-text">{String(pack.data.content || "")}</p>
          ) : (
            <DetailsList data={pack.data?.pack} />
          )}
        </details>
      ))}
      <form
        className="v2-upload"
        onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          void work.perform(async () => {
            const result = await command(
              `/applications/${application.id}/reflections`,
              { content: data.get("content") },
            );
            form.reset();
            return result;
          });
        }}
      >
        <label>
          记录真实问题、回答困难点和待补证据
          <textarea name="content" required rows={4} />
        </label>
        <button className="jd-outline-button" disabled={work.busy}>
          保存复盘
        </button>
      </form>
    </section>
  );
}
