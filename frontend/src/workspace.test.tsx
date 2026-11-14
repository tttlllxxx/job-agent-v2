import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { api, ApiError } from "./api";

const goal = {
  id: 1,
  revision: 1,
  name: "产品实习",
  direction: "AI 产品经理",
  recruitment_type: "日常实习",
  constraints: {},
  preferences: { cities: ["上海"] },
};
let applications: any[];
let patchFails = false;
const clients: QueryClient[] = [];
beforeEach(() => {
  localStorage.clear();
  patchFails = false;
  applications = [
    {
      id: 7,
      revision: 1,
      company: "测试公司",
      title: "产品实习生",
      city: "上海",
      stage: "已投递",
      applied_at: "2026-11-01",
      next_action: "等待进展",
      material: "产品简历.pdf",
      notes: "原备注",
      submitted_materials: {},
    },
  ];
  Element.prototype.scrollIntoView = vi.fn();
  window.scrollTo = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      let result: unknown = {};
      let status = 200;
      if (path === "/api/goals") result = [goal];
      if (path === "/api/status")
        result = { model_ready: true, search_ready: false };
      if (path === "/api/applications")
        result = {
          items: applications,
          total: applications.length,
          next_offset: null,
        };
      if (path === "/api/applications/7" && options?.method === "PATCH") {
        if (patchFails) {
          status = 409;
          result = { message: "记录已更新，请核对最新内容" };
        } else {
          const changes = JSON.parse(String(options.body));
          applications[0] = { ...applications[0], ...changes, revision: 2 };
          result = applications[0];
        }
      }
      if (path === "/api/workspace")
        result = {
          actions: [],
          inbox: [],
          runs: [],
          subscriptions: [],
          counts: { jobs: 0, applications: 1, goals: 1 },
        };
      if (path === "/api/jobs")
        result = { items: [], total: 0, next_offset: null };
      if (
        [
          "/api/attachments",
          "/api/threads",
          "/api/usage",
          "/api/legacy/external_mail_events",
          "/api/legacy/automation_schedules",
        ].includes(path)
      )
        result = [];
      if (path === "/api/threads/4")
        result = {
          id: 4,
          title: "历史对话",
          active_goal_id: 1,
          messages: [],
          runs: [{ id: 12, kind: "discovery", status: "waiting_user" }],
        };
      if (path === "/api/runs/12")
        result = {
          id: 12,
          kind: "discovery",
          status: "waiting_user",
          updated_at: "2026-11-12T00:00:00Z",
          events: [],
          result: {},
          error: "",
        };
      if (path === "/api/settings")
        result = {
          llm_provider: "api",
          llm_model: "test-model",
          llm_base_url: "https://example.com/v1",
          llm_api_key: { configured: true },
          search_api_key: { configured: false },
          feishu_webhook: { configured: false },
        };
      return new Response(JSON.stringify(result), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  clients.forEach((client) => client.clear());
  clients.length = 0;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function open(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("真实工作台入口", () => {
  it("正常入口显示持久化台账，修改携带当前版本并保存到 API", async () => {
    open("/applications");
    const cell = await screen.findByRole("button", {
      name: "编辑测试公司的备注",
    });
    fireEvent.click(cell);
    const input = screen.getByRole("textbox", { name: "编辑测试公司的备注" });
    fireEvent.change(input, { target: { value: "准备项目介绍" } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "编辑测试公司的备注" }),
      ).toHaveTextContent("准备项目介绍"),
    );
    const fetch = vi.mocked(globalThis.fetch);
    expect(
      fetch.mock.calls.some(
        ([url, options]) =>
          String(url) === "/api/applications/7" &&
          JSON.parse(String(options?.body)).expected_revision === 1,
      ),
    ).toBe(true);
  });
  it("保存冲突显示错误并保留用户编辑草稿", async () => {
    patchFails = true;
    open("/applications");
    fireEvent.click(
      await screen.findByRole("button", { name: "编辑测试公司的备注" }),
    );
    const input = screen.getByRole("textbox", { name: "编辑测试公司的备注" });
    fireEvent.change(input, { target: { value: "未保存的修改" } });
    fireEvent.blur(input);
    expect(await screen.findByRole("alert")).toHaveTextContent("记录已更新");
    expect(
      screen.getByRole("textbox", { name: "编辑测试公司的备注" }),
    ).toHaveValue("未保存的修改");
  });
  it("搜索与排序交由完整记录查询执行", async () => {
    open("/applications");
    await screen.findByRole("table");
    fireEvent.change(screen.getByLabelText("搜索申请记录"), {
      target: { value: "测试" },
    });
    fireEvent.change(screen.getByLabelText("申请排序"), {
      target: { value: "newest" },
    });
    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([url]) =>
              String(url).includes("query=%E6%B5%8B%E8%AF%95") &&
              String(url).includes("sort=newest"),
          ),
      ).toBe(true),
    );
  });
  it("刷新入口恢复筛选与排序，切换视图回到第一页", async () => {
    open(
      "/applications?query=测试&stage=一面&view=面试安排&sort=newest&offset=100",
    );
    expect(
      await screen.findByRole("combobox", { name: "申请排序" }),
    ).toHaveValue("newest");
    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([url]) =>
              String(url).includes("offset=100") &&
              String(url).includes("stage=%E4%B8%80%E9%9D%A2"),
          ),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole("button", { name: "▦ 全部申请" }));
    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([url]) =>
              String(url).includes("offset=0") &&
              String(url).includes(
                "view=%E5%85%A8%E9%83%A8%E7%94%B3%E8%AF%B7",
              ) &&
              String(url).includes("sort=newest") &&
              String(url).includes("stage=%E4%B8%80%E9%9D%A2"),
          ),
      ).toBe(true),
    );
  });
  it("重新进入会话后展示已保存的任务进度", async () => {
    open("/assistant/4");
    expect(await screen.findByText("等待你处理")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "从记录继续" }),
    ).toBeInTheDocument();
  });
  it("空机会页显示真实空态与继续入口", async () => {
    open("/opportunities");
    expect(
      await screen.findByRole("heading", { name: "当前范围没有岗位" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "联网找新机会" })).toBeEnabled();
  });
  it("设置显示已保存凭据状态并保留空输入", async () => {
    open("/settings");
    const input = await screen.findByPlaceholderText("已保存，输入可替换");
    expect(input).toHaveValue("");
    expect(screen.getByDisplayValue("test-model")).toBeInTheDocument();
  });
  it("API 错误保留状态并要求客户端标识", async () => {
    patchFails = true;
    await expect(
      api("/applications/7", { method: "PATCH", body: "{}" }),
    ).rejects.toBeInstanceOf(ApiError);
    const last = vi.mocked(fetch).mock.calls.at(-1)![1];
    expect(
      (last?.headers as Record<string, string>)["X-Workspace-Client"],
    ).toBe("job-agent");
  });
});
