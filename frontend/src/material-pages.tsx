import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, command, operationId } from "./api";
import { Empty, ErrorNotice, Heading, Modal } from "./components";
import { useWork } from "./hooks";
import { Attachments } from "./data-tools";
import type { Fact, Material, MaterialVersion, Profile, Resume } from "./types";

export function ProfilePage() {
  const work = useWork();
  const [params] = useSearchParams();
  const [resumeId, setResumeId] = useState(
    () => Number(params.get("resume")) || 0,
  );
  const [editingFact, setEditingFact] = useState<Fact | null>(null);
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => api<Profile>("/profile"),
  });
  const resumes = useQuery({
    queryKey: ["resumes"],
    queryFn: () => api<Resume[]>("/resumes"),
  });
  const activeId =
    resumeId ||
    resumes.data?.find((resume) => resume.active)?.id ||
    resumes.data?.[0]?.id;
  const selected = resumes.data?.find((resume) => resume.id === activeId);
  const facts = useQuery({
    queryKey: ["facts", activeId],
    queryFn: () => api<Fact[]>(`/facts?resume_id=${activeId}`),
    enabled: !!activeId,
  });
  const toggle = (fact: Fact, confirmed: boolean) =>
    work.perform(() =>
      command(
        `/facts/${fact.id}`,
        {
          expected_revision: fact.revision,
          key: fact.key,
          value: fact.value,
          confirmed,
          active: fact.active,
          resume_id: fact.resume_id,
          source_ref: fact.source_ref,
          metadata_: fact.metadata_,
        },
        "PATCH",
      ),
    );
  return (
    <>
      <Heading
        title="我的资料"
        description="个人条件、基础简历和可用于申请的事实"
      />
      {work.error && <ErrorNotice error={work.error} />}
      <div className="v2-profile-grid">
        <section className="jd-section">
          <h2>个人条件</h2>
          {profile.error && <ErrorNotice error={profile.error} />}{" "}
          {profile.data && (
            <form
              className="v2-settings-form"
              key={profile.data.revision}
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                const value = {
                  ...profile.data!.data,
                  graduation_year: data.get("graduation_year") || null,
                  graduation_date: data.get("graduation_date") || null,
                  days_per_week: data.get("days")
                    ? Number(data.get("days"))
                    : null,
                  duration_months: data.get("duration")
                    ? Number(data.get("duration"))
                    : null,
                  available_from: data.get("available") || null,
                  in_school:
                    data.get("in_school") === "unknown"
                      ? null
                      : data.get("in_school") === "yes",
                };
                void work.perform(() =>
                  command(
                    "/profile",
                    { expected_revision: profile.data!.revision, data: value },
                    "PATCH",
                  ),
                );
              }}
            >
              <label>
                毕业年份
                <input
                  name="graduation_year"
                  type="number"
                  min="1900"
                  max="2100"
                  defaultValue={String(profile.data.data.graduation_year || "")}
                />
              </label>
              <label>
                准确毕业日期
                <input
                  name="graduation_date"
                  type="date"
                  defaultValue={String(profile.data.data.graduation_date || "")}
                />
              </label>
              <label>
                在校身份
                <select
                  name="in_school"
                  defaultValue={
                    profile.data.data.in_school == null
                      ? "unknown"
                      : profile.data.data.in_school
                        ? "yes"
                        : "no"
                  }
                >
                  <option value="unknown">待确认</option>
                  <option value="yes">在校生</option>
                  <option value="no">已毕业</option>
                </select>
              </label>
              <label>
                每周到岗天数
                <input
                  name="days"
                  type="number"
                  min="0"
                  max="7"
                  defaultValue={String(profile.data.data.days_per_week ?? "")}
                />
              </label>
              <label>
                可实习月数
                <input
                  name="duration"
                  type="number"
                  min="0"
                  defaultValue={String(profile.data.data.duration_months ?? "")}
                />
              </label>
              <label>
                最早到岗日期
                <input
                  name="available"
                  type="date"
                  defaultValue={String(profile.data.data.available_from || "")}
                />
              </label>
              <button className="jd-button" disabled={work.busy}>
                保存并应用到全部目标
              </button>
            </form>
          )}
        </section>
        <section className="jd-section">
          <div className="jd-section-title">
            <h2>简历与原始文件</h2>
          </div>
          {resumes.error && <ErrorNotice error={resumes.error} />}
          <form
            className="v2-upload"
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const data = new FormData(form);
              void work.perform(async () => {
                const result = await api<Resume>("/resumes/import", {
                  method: "POST",
                  body: data,
                });
                setResumeId(result.id);
                form.reset();
                return result;
              });
            }}
          >
            <label>
              导入 PDF、DOCX、Markdown 或纯文本
              <input
                type="file"
                name="file"
                accept=".pdf,.docx,.md,.txt"
                required
              />
            </label>
            <button className="jd-outline-button" disabled={work.busy}>
              导入并检查事实
            </button>
          </form>
          {resumes.data?.map((resume) => (
            <article className="v2-record-row" key={resume.id}>
              <div>
                <button
                  className="jd-text-button"
                  onClick={() => setResumeId(resume.id)}
                >
                  {resume.name}
                </button>
                <small>{resume.active ? "当前活动版本" : "历史版本"}</small>
              </div>
              <div className="v2-actions">
                <a
                  href={`/api/resumes/${resume.id}/file`}
                  target="_blank"
                  rel="noreferrer"
                >
                  原文件
                </a>
                {!resume.active && (
                  <button
                    onClick={() =>
                      void work.perform(() =>
                        command(
                          `/resumes/${resume.id}`,
                          { active: true },
                          "PATCH",
                        ),
                      )
                    }
                  >
                    设为活动简历
                  </button>
                )}
              </div>
            </article>
          ))}
        </section>
      </div>
      {selected && (
        <section className="jd-section v2-spaced">
          <div className="jd-section-title">
            <h2>{selected.name} · 提取事实与修正</h2>
            <small>
              {facts.data?.filter((fact) => fact.confirmed && fact.active)
                .length || 0}{" "}
              条已确认
            </small>
          </div>
          <p className="jd-subtle">
            材料建议只引用已确认事实。选择字段用途后，辅助填写可复用该值。
          </p>
          <details>
            <summary>查看原始解析文字</summary>
            <div className="v2-long-text">{selected.text}</div>
          </details>
          {facts.error && <ErrorNotice error={facts.error} />}
          <div className="v2-fact-list">
            {facts.data
              ?.filter((fact) => fact.active)
              .map((fact) => (
                <article key={fact.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={fact.confirmed}
                      disabled={work.busy}
                      onChange={(event) =>
                        void toggle(fact, event.target.checked)
                      }
                    />
                    确认可用于申请
                  </label>
                  <p>{fact.value}</p>
                  <small>
                    {fact.source_ref} ·{" "}
                    {String(fact.metadata_.field_key || "经历原文")}
                  </small>
                  <button
                    className="jd-text-button"
                    onClick={() => setEditingFact(fact)}
                  >
                    修改内容与用途
                  </button>
                </article>
              ))}
          </div>
        </section>
      )}
      <Attachments />
      {editingFact && (
        <Modal title="修正事实" close={() => setEditingFact(null)}>
          <form
            className="jd-modal-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              void work.perform(async () => {
                const result = await command(
                  `/facts/${editingFact.id}`,
                  {
                    expected_revision: editingFact.revision,
                    key: editingFact.key,
                    value: data.get("value"),
                    confirmed: data.get("confirmed") === "on",
                    active: true,
                    resume_id: editingFact.resume_id,
                    source_ref: "user_correction",
                    metadata_: {
                      ...editingFact.metadata_,
                      field_key: data.get("field_key"),
                    },
                  },
                  "PATCH",
                );
                setEditingFact(null);
                return result;
              });
            }}
          >
            <label>
              确认内容
              <textarea
                name="value"
                required
                defaultValue={editingFact.value}
                rows={5}
              />
            </label>
            <label>
              可复用字段用途
              <select
                name="field_key"
                defaultValue={String(editingFact.metadata_.field_key || "")}
              >
                <option value="">经历或其他原文</option>
                {[
                  ["name", "姓名"],
                  ["email", "邮箱"],
                  ["phone", "电话"],
                  ["school", "学校"],
                  ["major", "专业"],
                  ["degree", "学历"],
                  ["graduation", "毕业时间"],
                  ["city", "城市"],
                  ["github", "GitHub"],
                ].map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="jd-checkbox">
              <input
                type="checkbox"
                name="confirmed"
                defaultChecked={editingFact.confirmed}
              />
              确认后用于材料与填写
            </label>
            <button className="jd-button" disabled={work.busy}>
              保存修正
            </button>
            <button
              type="button"
              className="jd-text-button"
              onClick={() =>
                void work.perform(async () => {
                  const result = await api(`/facts/${editingFact.id}`, {
                    method: "DELETE",
                  });
                  setEditingFact(null);
                  return result;
                })
              }
            >
              删除此事实
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

export function MaterialWorkspace() {
  const { materialId } = useParams();
  const work = useWork();
  const [editing, setEditing] = useState(false);
  const query = useQuery({
    queryKey: ["material", materialId],
    queryFn: () => api<Material>(`/materials/${materialId}`),
  });
  const material = query.data;
  if (query.error)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (!material) return <p role="status">正在读取材料…</p>;
  const updateSuggestion = (id: string, decision: string, edited?: string) =>
    work.perform(() =>
      command(
        `/materials/${material.id}`,
        {
          expected_revision: material.revision,
          suggestions: material.suggestions.map((suggestion) =>
            suggestion.id === id
              ? {
                  ...suggestion,
                  decision,
                  ...(edited != null ? { edited } : {}),
                }
              : suggestion,
          ),
        },
        "PATCH",
      ),
    );
  const preview = material.suggestions.reduce(
    (content, suggestion) =>
      suggestion.decision === "accepted"
        ? content.replace(
            suggestion.original,
            suggestion.edited || suggestion.proposed,
          )
        : content,
    material.content,
  );
  return (
    <>
      <Heading
        title="岗位申请材料"
        description={`${material.job?.company || ""} · ${material.job?.title || ""}`}
      >
        <Link className="jd-outline-button" to={`/jobs/${material.job_id}`}>
          岗位与依据
        </Link>
      </Heading>
      {work.error && <ErrorNotice error={work.error} />}{" "}
      {material.stale && (
        <div className="v2-error">
          基础简历或 JD 已更新，旧建议需要重新核对。历史版本已保留。
        </div>
      )}
      {material.status === "needs_facts" && (
        <div className="v2-error">
          当前没有已确认的简历事实，请先在资料页核对内容。
          <Link to="/profile">去确认事实 →</Link>
        </div>
      )}
      <div className="v2-material-layout">
        <section className="jd-section">
          <h2>逐条核对建议</h2>
          {!material.suggestions.length && (
            <Empty title="当前没有可用的修改建议">
              <Link to="/profile">确认或补充事实</Link>
            </Empty>
          )}
          {material.suggestions.map((suggestion) => (
            <article className="jd-material-suggestion" key={suggestion.id}>
              <h3>{suggestion.reason}</h3>
              <div className="jd-diff-old">
                <small>原文</small>
                <p>{suggestion.original}</p>
              </div>
              <div className="jd-diff-new">
                <small>建议</small>
                <p>{suggestion.proposed}</p>
              </div>
              <p className="jd-subtle">
                依据事实 #{suggestion.fact_ids.join("、#")}
              </p>
              <textarea
                aria-label={`编辑建议${suggestion.id}`}
                defaultValue={suggestion.edited || suggestion.proposed}
                key={suggestion.id + suggestion.edited}
                onBlur={(event) => {
                  if (
                    event.target.value !==
                    (suggestion.edited || suggestion.proposed)
                  )
                    void updateSuggestion(
                      suggestion.id,
                      "accepted",
                      event.target.value,
                    );
                }}
              />
              <div className="v2-actions">
                <button
                  className={
                    suggestion.decision === "accepted"
                      ? "jd-button"
                      : "jd-outline-button"
                  }
                  disabled={work.busy}
                  onClick={() =>
                    void updateSuggestion(suggestion.id, "accepted")
                  }
                >
                  采纳
                </button>
                <button
                  disabled={work.busy}
                  onClick={() =>
                    void updateSuggestion(suggestion.id, "rejected")
                  }
                >
                  保留原文
                </button>
              </div>
            </article>
          ))}
        </section>
        <section className="jd-section">
          <div className="jd-section-title">
            <h2>最终预览</h2>
            <button
              className="jd-text-button"
              onClick={() => setEditing(!editing)}
            >
              {editing ? "退出全文编辑" : "编辑全文"}
            </button>
          </div>
          {editing ? (
            <textarea
              className="v2-document-editor"
              defaultValue={material.content}
              onBlur={(event) => {
                if (event.target.value !== material.content)
                  void work.perform(() =>
                    command(
                      `/materials/${material.id}`,
                      {
                        expected_revision: material.revision,
                        content: event.target.value,
                      },
                      "PATCH",
                    ),
                  );
              }}
            />
          ) : (
            <div className="v2-document-preview">{preview}</div>
          )}
          <button
            className="jd-button"
            disabled={work.busy}
            onClick={() =>
              void work.perform(() =>
                command<MaterialVersion>(`/materials/${material.id}/versions`, {
                  operation_id: operationId(),
                  expected_revision: material.revision,
                }),
              )
            }
          >
            保存固定材料版本
          </button>
          <h3>历史版本与下载</h3>
          {material.versions?.map((version) => (
            <div className="v2-record-row" key={version.id}>
              <span>版本 #{version.id}</span>
              <div className="v2-actions">
                {["pdf", "docx", "md"].map((format) => (
                  <a
                    key={format}
                    href={`/api/material-versions/${version.id}/download?format=${format}`}
                  >
                    {format.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}
