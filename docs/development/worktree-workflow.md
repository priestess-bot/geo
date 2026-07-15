# Worktree 与合并规范

整改采用短生命周期 worktree，Foundation 先合并，数据、API、前端和基础设施再并行。每个分支只拥有明确目录，禁止多人同时拆同一个巨型文件。

```bash
git worktree add ../geo-remediation-data -b codex/remediation-data main
git worktree add ../geo-remediation-api -b codex/remediation-api main
git worktree add ../geo-remediation-web -b codex/remediation-web main
```

每个提交只包含一种结构变换，并附直接测试。固定合并顺序：Foundation → Data/Auth → Domain → API → Frontend/Development Board → Cleanup/Docs。发生冲突时由主会话基于领域合同解决，不通过覆盖或回退其他 worktree 的修改解决。

分支合并后确认没有未提交修改，再移除 worktree。任何带修改的 worktree 都必须先提交、保留或明确审计，不能直接删除。
