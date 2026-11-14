import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { api } from "./api";
import { ErrorNotice, GoalSelect, Icon } from "./components";
import { Today, Assistant, Opportunities, JobDetail } from "./discovery-pages";
import {
  Applications,
  ApplicationDetail,
  FillWorkspace,
} from "./application-pages";
import {
  Goals,
  Subscriptions,
  SubscriptionDetail,
  InboxPage,
  RunsPage,
  SourcesPage,
  SettingsPage,
} from "./management-pages";
import { ProfilePage, MaterialWorkspace } from "./material-pages";
import type { Goal } from "./types";

export function App() {
  const goalsQuery = useQuery({
    queryKey: ["goals"],
    queryFn: () => api<Goal[]>("/goals"),
  });
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () =>
      api<{ model_ready: boolean; search_ready: boolean }>("/status"),
  });
  const [goalId, setGoalId] = useState<number | null>(
    () => Number(localStorage.getItem("job-agent.goal")) || null,
  );
  const [mobile, setMobile] = useState(false);
  const location = useLocation();
  const goals = goalsQuery.data || [];
  useEffect(() => {
    if (goalsQuery.data)
      setGoalId((current) =>
        goalsQuery.data.some((goal) => goal.id === current)
          ? current
          : (goalsQuery.data[0]?.id ?? null),
      );
  }, [goalsQuery.dataUpdatedAt]);
  useEffect(() => {
    if (goalId) localStorage.setItem("job-agent.goal", String(goalId));
  }, [goalId]);
  useEffect(() => {
    setMobile(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  const navigation = [
    { path: "/today", name: "今日", icon: "today" },
    { path: "/assistant", name: "求职助手", icon: "assistant" },
    { path: "/opportunities", name: "机会", icon: "opportunities" },
    { path: "/applications", name: "申请", icon: "applications" },
  ];
  const selected = goals.find((goal) => goal.id === goalId);
  const context = { goals, goalId, setGoalId };
  return (
    <div className="job-demo">
      <aside className={`jd-sidebar ${mobile ? "is-open" : ""}`}>
        <Link className="jd-brand" to="/today">
          <span className="jd-brand-symbol">
            j<span>·</span>
          </span>
          <span>
            职序<small>JOB AGENT</small>
          </span>
        </Link>
        <Link className="jd-new-task v2-nav-action" to="/assistant?new=1">
          <Icon name="plus" />
          开始新的探索
        </Link>
        <div className="jd-nav-label">工作空间</div>
        <nav aria-label="主要导航">
          {navigation.map((item) => (
            <NavLink
              className={({ isActive }) =>
                `v2-nav-link ${isActive ? "active" : ""}`
              }
              key={item.path}
              to={item.path}
            >
              <Icon name={item.icon} />
              {item.name}
            </NavLink>
          ))}
        </nav>
        <div className="jd-sidebar-goal">
          <div className="jd-nav-label">正在关注</div>
          <Link className="v2-goal-link" to="/goals">
            <span className="jd-goal-dot" />
            {selected?.name || "建立求职目标"}
          </Link>
          <Link className="v2-secondary-link" to="/subscriptions">
            管理订阅
          </Link>
          <Link className="v2-secondary-link" to="/companies">
            关注公司
          </Link>
        </div>
        <div className="jd-sidebar-bottom">
          <nav aria-label="资料与设置">
            <NavLink className="v2-nav-link" to="/profile">
              <Icon name="profile" />
              我的资料
            </NavLink>
            <NavLink className="v2-nav-link" to="/settings">
              <Icon name="settings" />
              设置
            </NavLink>
          </nav>
          <div className="jd-local">
            <span className="jd-live-dot" />
            <span>
              本地工作台<small>个人数据保存在本机</small>
            </span>
            <span className="jd-avatar">你</span>
          </div>
        </div>
      </aside>
      {mobile && (
        <button
          className="jd-mobile-backdrop"
          aria-label="收起导航"
          onClick={() => setMobile(false)}
        />
      )}
      <div className="jd-workspace">
        <header className="jd-topbar">
          <div>
            <button
              className="jd-icon-button jd-mobile-menu"
              aria-label="打开导航"
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              <Icon name="menu" />
            </button>
            <span>我的工作空间</span>
            <span>›</span>
            <strong>
              {navigation.find((item) =>
                location.pathname.startsWith(item.path),
              )?.name || "资料与管理"}
            </strong>
          </div>
          <div>
            <Link to="/settings">
              {status.data?.model_ready ? "模型已配置" : "配置模型"}
            </Link>
            <Link to="/inbox" aria-label="通知记录">
              <Icon name="bell" />
            </Link>
            <Link to="/runs">运行记录</Link>
          </div>
        </header>
        <main className="jd-main">
          {goalsQuery.error ? (
            <ErrorNotice
              error={goalsQuery.error}
              retry={() => void goalsQuery.refetch()}
            />
          ) : goalsQuery.isPending ? (
            <div role="status">正在读取求职工作台…</div>
          ) : (
            <Routes>
              <Route
                path="/"
                element={
                  <Navigate
                    replace
                    to={goals.length ? "/today" : "/assistant"}
                  />
                }
              />
              <Route path="/today" element={<Today {...context} />} />
              <Route path="/assistant" element={<Assistant {...context} />} />
              <Route
                path="/assistant/:threadId"
                element={<Assistant {...context} />}
              />
              <Route
                path="/opportunities"
                element={<Opportunities {...context} />}
              />
              <Route path="/jobs/:jobId" element={<JobDetail {...context} />} />
              <Route path="/applications" element={<Applications />} />
              <Route
                path="/applications/:applicationId"
                element={<ApplicationDetail />}
              />
              <Route
                path="/applications/:applicationId/fill"
                element={<FillWorkspace />}
              />
              <Route path="/goals" element={<Goals {...context} />} />
              <Route
                path="/companies"
                element={<Goals {...context} companiesOnly />}
              />
              <Route
                path="/subscriptions"
                element={<Subscriptions {...context} />}
              />
              <Route
                path="/subscriptions/:subscriptionId"
                element={<SubscriptionDetail />}
              />
              <Route path="/profile" element={<ProfilePage />} />
              <Route
                path="/materials/:materialId"
                element={<MaterialWorkspace />}
              />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/runs" element={<RunsPage />} />
              <Route path="/sources" element={<SourcesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route
                path="/demo/*"
                element={<Navigate to="/today" replace />}
              />
              <Route path="*" element={<Navigate to="/today" replace />} />
            </Routes>
          )}
          <footer className="jd-footer">
            <span>职序 · 个人求职工作台</span>
            <span>本地运行 · 来源与执行结果可追溯</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
