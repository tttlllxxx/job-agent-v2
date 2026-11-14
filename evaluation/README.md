# 验证记录

v2 的行为验证使用根目录 `tests/test_workspace.py`、前端 `workspace.test.tsx` 和 Agent 协议测试。执行命令见 [README](../README.md#验证)，结果及外部验收缺口见 [重构状态](../docs/REBUILD_STATUS.md)。

`datasets`、`reports` 和邮件示例保留为历史评测资料。旧评测脚本依赖已经移除的 v1 实现，不再用于新版验收。`product-observations.csv` 继续用于人工实测，空白表示未测，不能解释为零。
