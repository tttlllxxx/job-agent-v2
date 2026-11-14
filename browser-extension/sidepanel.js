const elements = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map((element) => [
    element.id,
    element,
  ]),
);
let applications = [];
let session;
let snapshot;
let boundTab;
let busy = false;
const base = "http://127.0.0.1:8000/api";

async function api(path, body, method = "POST") {
  const response = await fetch(base + path, {
    method: body === undefined ? "GET" : method,
    headers: {
      "Content-Type": "application/json",
      "X-Workspace-Client": "job-agent",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || "请求未完成");
  return result;
}
function status(message, error = false) {
  elements.status.textContent = message;
  elements.status.className = error ? "error" : "";
}
async function perform(action) {
  if (busy) return;
  busy = true;
  elements.scan.disabled = true;
  elements.fill.disabled = true;
  try {
    await action();
  } catch (error) {
    status(error.message, true);
  } finally {
    busy = false;
    elements.scan.disabled = false;
    elements.fill.disabled = !snapshot;
  }
}
function option(label, value) {
  const element = document.createElement("option");
  element.textContent = label;
  element.value = String(value);
  return element;
}

async function initialize() {
  let offset = 0;
  do {
    const result = await api(`/applications?offset=${offset}&limit=500`);
    applications.push(...result.items);
    offset = result.next_offset;
  } while (offset !== null);
  elements.application.replaceChildren(
    option("选择当前申请", ""),
    ...applications.map((app) =>
      option(`${app.company} · ${app.title}`, app.id),
    ),
  );
  const resumes = await api("/resumes");
  elements.resume.append(
    ...resumes.map((resume) => option(resume.name, resume.id)),
  );
  const stored = await chrome.storage.local.get("applicationId");
  if (applications.some((app) => app.id === stored.applicationId))
    elements.application.value = stored.applicationId;
}

function scanPage() {
  const controls = [
    ...document.querySelectorAll("input,textarea,select"),
  ].filter(
    (element) =>
      !["hidden", "submit", "button", "password", "file"].includes(
        element.type,
      ) &&
      element.getClientRects().length &&
      getComputedStyle(element).visibility !== "hidden",
  );
  const fields = controls.map((element, index) => ({
    key: `${element.id || element.name || "field"}::${index}`,
    index,
    label:
      element.labels?.[0]?.innerText ||
      element.getAttribute("aria-label") ||
      element.placeholder ||
      element.name ||
      `字段 ${index + 1}`,
    type: element.type || element.tagName.toLowerCase(),
    required: element.required,
    has_value: ["checkbox", "radio"].includes(element.type)
      ? element.checked
      : Boolean(element.value),
    value: ["checkbox", "radio"].includes(element.type)
      ? element.checked
      : element.value,
    options: element.options
      ? [...element.options].map((option) => ({
          label: option.text,
          value: option.value,
        }))
      : [],
  }));
  const blockers = [];
  if (document.querySelector("input[type=password]"))
    blockers.push("页面需要登录，请在官网完成");
  if (/验证码|captcha|人机验证/i.test(document.body.innerText))
    blockers.push("请核对页面验证码");
  return { url: location.href, fields, blockers };
}
function fillPage(approval) {
  if (location.href !== approval.url) throw new Error("页面已变化，请重新扫描");
  const controls = [
    ...document.querySelectorAll("input,textarea,select"),
  ].filter(
    (element) =>
      !["hidden", "submit", "button", "password", "file"].includes(
        element.type,
      ) &&
      element.getClientRects().length &&
      getComputedStyle(element).visibility !== "hidden",
  );
  const keys = controls.map(
    (element, index) => `${element.id || element.name || "field"}::${index}`,
  );
  if (
    JSON.stringify(keys) !==
    JSON.stringify(approval.fields.map((field) => field.key))
  )
    throw new Error("表单结构已变化，请重新扫描");
  for (const action of approval.actions) {
    const element = controls[action.index];
    const old = approval.fields.find((field) => field.key === action.key);
    const label =
      element.labels?.[0]?.innerText ||
      element.getAttribute("aria-label") ||
      element.placeholder ||
      element.name ||
      `字段 ${action.index + 1}`;
    if (label !== old.label || element.type !== old.type)
      throw new Error("字段含义已变化，请重新扫描");
    if (
      !approval.overwrite?.includes(action.key) &&
      String(
        ["checkbox", "radio"].includes(element.type)
          ? element.checked
          : element.value,
      ) !== String(old.value ?? "")
    )
      throw new Error("字段已有值变化，请重新扫描并核对");
  }
  return approval.actions.map((action) => {
    const element = controls[action.index];
    if (["checkbox", "radio"].includes(element.type))
      element.checked = ["true", "yes", "1", "是"].includes(
        String(action.value).toLowerCase(),
      );
    else if (element.tagName === "SELECT") {
      const option = [...element.options].find(
        (option) =>
          option.value === String(action.value) ||
          option.text === String(action.value),
      );
      if (!option) return { key: action.key, verified: false };
      element.value = option.value;
    } else {
      const prototype =
        element.tagName === "TEXTAREA"
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value").set.call(
        element,
        String(action.value),
      );
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return {
      key: action.key,
      verified: ["checkbox", "radio"].includes(element.type)
        ? element.checked ===
          ["true", "yes", "1", "是"].includes(
            String(action.value).toLowerCase(),
          )
        : String(element.value) === String(action.value) ||
          element.tagName === "SELECT",
    };
  });
}
function renderPreview() {
  elements.fields.replaceChildren();
  for (const field of snapshot.preview) {
    const article = document.createElement("article");
    article.dataset.key = field.key;
    const label = document.createElement("label");
    const checked = document.createElement("input");
    checked.type = "checkbox";
    checked.className = "selected";
    checked.checked = field.state === "ready";
    label.append(
      checked,
      document.createTextNode(field.label + (field.required ? " · 必填" : "")),
    );
    const metadata = document.createElement("small");
    metadata.textContent = `${{ ready: "拟填写", existing: "已有值", missing: "缺少答案", sensitive: "需单独授权" }[field.state] || field.state} · ${field.source ? "已保存的资料或答案" : "请补充答案"}`;
    const answer = document.createElement("input");
    answer.className = "answer";
    answer.value = field.proposed ?? "";
    answer.setAttribute("aria-label", field.label + "答案");
    article.append(label, metadata, answer);
    for (const [needed, className, text] of [
      [field.sensitive, "sensitive", "授权填写该敏感字段"],
      [field.has_value, "overwrite", "允许覆盖页面已有值"],
    ]) {
      if (!needed) continue;
      const consent = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = className;
      consent.append(checkbox, document.createTextNode(text));
      article.append(consent);
    }
    elements.fields.append(article);
  }
}
elements.scan.addEventListener("click", () =>
  perform(async () => {
    const id = Number(elements.application.value);
    if (!id) throw new Error("请先选择当前申请");
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    boundTab = tabs[0];
    if (!boundTab?.url?.startsWith("http"))
      throw new Error("请打开 HTTP 或 HTTPS 网申页面");
    status("正在扫描当前页面…");
    session = await api(`/applications/${id}/fill-sessions`, {
      operation_id: crypto.randomUUID(),
      url: boundTab.url,
      executor: "extension",
    });
    const result = await chrome.scripting.executeScript({
      target: { tabId: boundTab.id },
      func: scanPage,
    });
    snapshot = await api(
      `/fill-sessions/${session.id}/snapshots`,
      result[0].result,
    );
    await chrome.storage.local.set({ applicationId: id });
    renderPreview();
    status(
      snapshot.blockers.length
        ? snapshot.blockers.join("；")
        : "扫描完成，请逐项核对后选择填写",
    );
  }),
);
elements.fill.addEventListener("click", () =>
  perform(async () => {
    if (!snapshot || !session) throw new Error("请先扫描当前页");
    const selected = [],
      sensitive = [],
      overwrite = [],
      answers = {};
    for (const article of elements.fields.querySelectorAll("article")) {
      const key = article.dataset.key;
      if (!article.querySelector(".selected").checked) continue;
      selected.push(key);
      answers[key] = article.querySelector(".answer").value;
      if (article.querySelector(".sensitive")?.checked) sensitive.push(key);
      if (article.querySelector(".overwrite")?.checked) overwrite.push(key);
    }
    const approval = await api(`/fill-sessions/${session.id}/execute`, {
      operation_id: crypto.randomUUID(),
      snapshot_id: snapshot.id,
      selected,
      sensitive,
      overwrite,
      answers,
    });
    try {
      const result = await chrome.scripting.executeScript({
        target: { tabId: boundTab.id },
        func: fillPage,
        args: [approval.data],
      });
      await api(`/approvals/${approval.id}/complete`, {
        url: snapshot.url,
        results: result[0].result,
      });
      status(
        `已填写并回读 ${result[0].result.filter((field) => field.verified).length} 项。请核对页面，跨页后继续扫描。`,
      );
    } catch (error) {
      await api(`/approvals/${approval.id}/complete`, {
        url: snapshot.url,
        error: error.message,
      }).catch(() => undefined);
      snapshot = undefined;
      throw error;
    }
  }),
);
elements.pause.addEventListener("click", () =>
  perform(async () => {
    if (session) await api(`/fill-sessions/${session.id}/pause`, {});
    status("已暂存，返回后重新扫描可继续");
  }),
);
elements.submitted.addEventListener("click", () =>
  perform(async () => {
    const id = Number(elements.application.value);
    if (!id || !elements.date.value || !elements.material.value.trim())
      throw new Error("请填写申请、实际投递日期和材料名称");
    if (!confirm("确认你已在官网完成当前岗位提交，并记录所选实际材料？"))
      return;
    await api(`/applications/${id}/submission-confirmations`, {
      operation_id: crypto.randomUUID(),
      applied_at: elements.date.value,
      materials: {
        resume_ids: elements.resume.value
          ? [Number(elements.resume.value)]
          : [],
        description: elements.material.value,
      },
      note: "用户通过扩展核对官网提交成功",
    });
    status("已保存实际提交结果与材料关联");
  }),
);
elements.application.addEventListener("change", () => {
  snapshot = undefined;
  session = undefined;
  boundTab = undefined;
  elements.fields.replaceChildren();
  elements.fill.disabled = true;
  status("申请已切换，请重新扫描当前页面");
});
void initialize().catch((error) => status(error.message, true));
