# 职序 · 个人求职 Agent

单用户本地工作台。通过对话维护求职目标，发现并核验岗位，订阅变化，审核材料，辅助填写并跟踪申请。前端使用浅色工作台和可直接编辑的申请表格，数据保存于本地 SQLite 和文件目录。

本仓库是 v2 重构版本的独立源码仓库，包含前后端、设计文档、网申插件及测试。克隆后首次启动会建立空工作台，个人数据保存在运行机器。

## 本地运行

需要 Python 3.12+、Node.js 22+。首次安装与启动如下。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
npm --prefix frontend ci
npm --prefix agent-runtime ci
cp .env.example .env
./scripts/start-local.sh
```

打开 [本地工作台](http://127.0.0.1:8000)。首次使用建立求职方向即可继续，个人资料和简历可随后补充。模型、搜索、飞书通知通过设置配置，已有凭据迁移后继续使用。界面中的岗位、申请、材料和会话读取实际数据库。

前端独立开发使用 `npm --prefix frontend run dev`，Vite 将 `/api` 代理到本地后端。

## 页面与流程

- 今日聚合待办、新提醒、运行和人工接管记录。
- 助手支持历史会话、当前目标、实际工具调用和持久化进度。
- 机会支持联网发现、链接导入、资格判断、来源证据、用户决定和完整分页。
- 目标、关注公司、订阅、检查历史与通知记录分别可管理。
- 申请表格支持单元格编辑、阶段单选、搜索、筛选、排序、字段显隐和分页，详情保存重复或自定义阶段及日期修订。
- 资料支持四类简历导入、事实修正与确认，材料支持建议采纳、全文编辑、固定版本和 PDF／DOCX／Markdown 下载。
- 填写支持 Chrome 扩展和可见 Playwright 浏览器，预览后授权所选字段，登录、验证码、文件上传与最终提交由用户处理。
- 设置提供模型能力检测、搜索与通知配置、来源健康、完整备份和迁移报告。

## 网申插件下载与安装

网申插件源码在 [browser-extension](browser-extension/)，可下载 [v2.0.0 插件 ZIP](https://github.com/tttlllxxx/job-agent-v2/releases/download/v2.0.0/zhixu-browser-extension-v2.0.0.zip)。

解压后打开 Chrome 的 `chrome://extensions`，启用开发者模式，点击“加载已解压的扩展程序”，选择包含 `manifest.json` 的目录。先启动本地工作台，再打开网申页面，点击插件图标使用侧栏。完整说明见[扩展安装文档](browser-extension/README.md)。

## 数据与迁移

运行库为 `data/workspace.db`。`data/uploads` 保存原始文件和附件，`data/generated` 保存固定材料版本，`data/backups` 保存用户创建的备份。此次重构的原库、旧源代码和停用缓存已移到项目外的回退目录，具体位置和迁移数量见[重构实施状态](docs/REBUILD_STATUS.md)。

已有 v1 数据使用以下命令导入独立的新库，原数据库保持可回退。

```bash
PYTHONPATH=backend .venv/bin/python -m app.migrate \
  --source data/app.db --target sqlite:///data/workspace.db
```

迁移保留个人资料、简历、事实、附件、岗位证据、申请与材料关联、时间线、对话、订阅及必要历史。每个岗位迁移最新推荐依据，旧评分缓存、登录会话和调用日志留在原始备份。订阅建立迁移基线，未完成浏览器任务重新扫描后继续。

备份恢复先校验并暂存，重启本地服务后切换。切换前会另存当前数据库，原始文件和材料一起恢复。备份包含个人信息及连接凭据。

## 连接与运行条件

搜索使用 Tavily，可在设置保存搜索 Key。请求字段按官方接口定义实现。网页详情通过可访问网页及模型提取，受限来源单独记录，结果保留来源和核验时间。[Tavily 接口说明](https://docs.tavily.com/documentation/api-reference/endpoint/search)

Node pi-agent 使用内存会话和业务工具白名单，通过 JSON-RPC 调用 Python。Python 保存目标、状态、授权和业务副作用。模型能力检测实际检查工具调用与流式输出。

本地服务运行期间检查订阅，重启合并补查并回到原约定时刻。无变化保持安静，发送超时保留送达未知。邮件和日历在用户启用后使用 macOS 系统应用，权限由系统管理。

扩展安装步骤见 [browser-extension/README.md](browser-extension/README.md)。Docker 提供采集、对话、材料、监控和台账服务，人工接管的可见浏览器及 macOS 连接使用本地运行环境。

## 验证

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
npm --prefix frontend test -- --run
npm --prefix frontend run build
npm --prefix agent-runtime test
node --test browser-extension/fields.test.cjs
```

测试使用隔离数据库和可控输入。真实渠道覆盖、登录后页面适配、完整外部网申和人工耗时记录按需求中的验收场景验证。

## 设计依据

- [需求分析](docs/REQUIREMENTS.md)
- [交互设计](docs/DESIGN.md)
- [技术设计](docs/TECHNICAL_PLAN.md)
- [界面规范](docs/UI_DESIGN_PROMPT.md)
- [重构实施状态](docs/REBUILD_STATUS.md)

## 许可证

MIT。依赖说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
