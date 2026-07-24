# 非 B 性能运行手册

本手册覆盖路线图中已实施的 A、C、D 工作流，不覆盖 B（连接器与归因）。它为
`performance-profile-v1-non-b` 提供可重复的执行和证据组合方式；任何缩量运行均为诊断，
不能勾选路线图中的性能验收项。

## 运行前

1. 使用隔离、受控的 staging 环境，不对现有开发或生产数据执行写负载。
2. 先验证冻结文件未被修改：

   ```bash
   make roadmap-performance-profile
   make roadmap-performance-workload
   git diff --exit-code -- benchmarks/roadmap/performance-profile-v1-non-b.json \
     benchmarks/roadmap/performance-workload-v1-non-b.json
   ```

3. 确认环境具有 4 个通用 Worker、1 个 Style Browser Worker、1 个 Relay、固定 Compose
   资源配额及 `GEO_DB_POOL_MAX_SIZE=10`。外部模型调用必须使用冻结 recording/受控 adapter，
   不能消耗实际 Provider 配额。
4. 创建专用 Project/Campaign 数据。压测 header 放在权限为 `0600` 的单行文件中，内容为
   `Authorization: Bearer ...`；该文件和写请求 JSON 不进入 Git、shell history、报告或
   evidence manifest。

## API 原始测量

完整运行固定为 30 分钟、20 read RPS、5 write RPS。下面命令需要显式确认，报告仅保存
脱敏 origin/path、状态汇总、延迟和 checksum，不保存 header、body 或 URL query。

```bash
make roadmap-performance-api-load PERF_ARGS="\
  --read-url https://internal-staging.example/v1/projects/PROJECT_ID/health-read \
  --write-url https://internal-staging.example/v1/projects/PROJECT_ID/controlled-write \
  --write-payload /run/geo/performance-write.json \
  --authorization-header-file /run/geo/performance-auth-header \
  --output artifacts/performance/raw-api-load.json \
  --confirm-controlled-performance-run"

make roadmap-performance-api-load-verify PERF_API_REPORT_ARGS="\
  artifacts/performance/raw-api-load.json \
  --read-url https://internal-staging.example/v1/projects/PROJECT_ID/health-read \
  --write-url https://internal-staging.example/v1/projects/PROJECT_ID/controlled-write"
```

只有 endpoint 连通性预检时，才允许显式缩量。它会被硬标记为 `diagnostic_only=true`：

```bash
make roadmap-performance-api-load PERF_ARGS="\
  --read-url https://internal-staging.example/health-read \
  --write-url https://internal-staging.example/controlled-write \
  --write-payload /run/geo/performance-write.json \
  --output artifacts/performance/diagnostic-api-load.json \
  --diagnostic-duration-seconds 30 --diagnostic-read-rps 1 --diagnostic-write-rps 1 \
  --confirm-controlled-performance-run"
```

## 完整结果与证据

API 原始报告不是最终性能结果。发布 owner 必须在同一运行窗口收集并写入
`geo-performance-result-v1`：

- 每个冻结 Sampling Run 的 1,000 planned/terminal Task、100 peak eligible 和 dispatch latency；
- 九个 Style Channel 的 200 样本、40 Case、160 Candidate、1,200 experiment slot 明细；
- Relay/outbox、最大 queue age、drain、1,000 Observation 的 metric recompute；
- Compose 拓扑和每个服务 CPU/内存 watermark；
- 跨 Project 读取、重复终态、丢失 outbox 和 hash mismatch 均为零；
- API raw report 的 URI、SHA-256、环境指纹、开始和结束时间。

最后执行：

```bash
make roadmap-performance-result-verify RESULT=artifacts/performance/result.json
```

该命令不信任 result 中自带的 `accepted` 字段，且会拒绝 profile/workload hash 不一致、缩量、
缺少单 Run/单 Channel 明细或低于请求/队列/计算样本量的结果。将 raw report、最终 result、
容器资源记录和 collector SQL/查询输出写入不可变对象存储，再在 evidence manifest 中引用
它们的 URI 与 SHA-256。

## 异常处理

- 请求调度无法按计划开始、完成数不足、5xx 或 transport failure 均保留在原始报告中；不要
  重写分母或只导出成功请求。
- 任一 keyring、Worker、Relay、MinIO、Valkey 或 PostgreSQL 健康异常时停止运行，保留故障
  时间窗并按故障演练记录处理；不得把部分运行拼接成一次通过。
- 完整运行失败后修复系统并重新使用相同 profile 运行。不要在 `v1` 中降低 RPS、项目、任务、
  工件或资源要求；需求变化必须创建预先批准的新 profile。
