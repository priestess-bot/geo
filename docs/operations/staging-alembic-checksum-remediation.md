# Staging Alembic checksum remediation

本手册只适用于已经独立确认的 staging 数据库，且数据库仍处于单一 head
`0095_synthetic_dify_closed_loop`。工具只把 `0093`、`0094`、`0095` 三条
`alembic_sql_checksum_ledger` 记录从内置旧 hash 改成内置、经复核的新 hash；它不执行
迁移 SQL，也不修改业务表或 schema。

没有 `--apply` 时命令只读。任何目标身份、备份、恢复、源码、schema、干跑收据或并发状态不
完全一致都会拒绝。不要用它处理 production、development、其他 head、其他 checksum drift，
也不要修改 allowlist 来让未知漂移通过。

## 0. 硬前提

在开始维护窗口前全部满足：

- 运行代码和 `0093` 至 `0095` SQL 已经 code review；工作树中的目标 hash 必须匹配工具内置
  destination allowlist。
- 部署清单中已有独立于目标数据库的 `environment=staging`、数据库名、installer 用户、
  PostgreSQL system identifier 和完整 Project ID 集合。不得在本次操作中查询目标后把查询
  结果当作“预期值”。
- staging 使用 [认证备份与恢复](backup-restore.md) 所述 production-equivalent Compose、五个
  MinIO bucket、历史 keyring 和恢复 canary。当前基于 `infra/docker-compose.yml` 的 development
  staging 栈不满足这项合同；必须先迁到 production-equivalent 配置。普通 `pg_dump`、复制
  volume、旧 v5 manifest 或任意 JSON 文件均不能代替此门禁。
- 备份 keyring、应用历史 keyring 和恢复 tmpfs 可用；操作者能够执行隔离恢复。
- 收据目录位于受控本地文件系统，由操作者持有且 mode `0700`。不要放在共享目录或网络盘。

以下变量均来自部署清单或受控配置，不从目标数据库临时生成：

```bash
export PROD_ENV=/secure/path/staging-production-equivalent.env
export DATABASE_URL_FILE=/secure/path/staging-installer-database-url
export BACKUP_KEYRING_FILE=/secure/path/backup-keyring.json
export EXPECTED_SYSTEM_IDENTIFIER='<inventory-system-identifier>'
export RECEIPT_ROOT=/secure/geo-remediation-receipts/<change-id>
install -d -m 0700 "$RECEIPT_ROOT"

# 必须按部署清单排序、逐项填写；每项最终映射为一个 --expected-project-id。
EXPECTED_PROJECT_IDS=(
  '<project-uuid-1>'
  '<project-uuid-2>'
)
```

`DATABASE_URL_FILE` 必须为操作者或 root 持有的普通文件、不可为 symlink、mode `0400` 或
`0600`。URL、密码、keyring 内容和 raw system identifier 不得写入工单、日志或收据。

## 1. 静默写入并生成认证备份

先停所有可能写 PostgreSQL 或 MinIO 的服务，包括 Internal/Customer API、Task Worker、
Outbox Relay、告警发送 Worker、Style Browser Worker 和迁移任务；保持 PostgreSQL 与 MinIO
运行。确认队列和数据库没有活跃应用写事务后才备份。Web 可以继续显示维护页，但不得继续接收
写操作。

使用部署实际的 Compose project/file 停止写入者。示例中的 service 列表需按该部署的
`docker compose config --services` 核对：

```bash
docker compose <staging-compose-args> stop \
  internal-api customer-api task-worker outbox-relay alert-smtp-relay
docker compose <staging-compose-args> ps
```

在整个备份、恢复、干跑、应用、Alembic 校验和后续升级期间保持这些写入者停止。然后创建显式
标记为 staging 的 v6 认证备份：

```bash
BACKUP_SOURCE_ENVIRONMENT=staging make backup PROD_ENV="$PROD_ENV"
export BACKUP_DIR=/secure/geo-backups/daily/<backup-id>

uv run python scripts/backup_manifest.py verify \
  --keyring "$BACKUP_KEYRING_FILE" \
  --backup-dir "$BACKUP_DIR" >/dev/null
```

有效 v6 manifest 会认证并冻结：源码 Alembic ledger、数据库内实际 ledger、database/user、
`environment=staging`、system identifier、完整 Project ID 集合，以及 PostgreSQL/MinIO/keyring
恢复所需证据。三条待修复记录必须仍为内置旧 hash。

## 2. 隔离恢复同一份备份

对上一步的完整 backup directory 执行生产等价空环境恢复：

```bash
sudo make restore-smoke PROD_ENV="$PROD_ENV" BACKUP_DIR="$BACKUP_DIR"
```

命令成功输出 `restore smoke passed: receipt=<path>`。记录这个精确路径：

```bash
export RESTORE_RECEIPT=/secure/geo-backups/restore-receipts/<backup-id>-<restore-id>.json
```

工具会再次验证 receipt 是 canonical 私有文件，并要求其 backup ID、manifest hash、0095
repository ledger、Project 数量、FK/关键表 hash、逐对象 hash，以及 Secret Store 历史 key
解密 canary 全部匹配。仅有 restore 命令退出码或数据库 dump 可读不构成证据。

## 3. 干跑并冻结计划

为 CLI 构造 Project 参数；数组顺序必须与部署清单中的 canonical UUID 排序一致：

```bash
PROJECT_ARGS=()
for project_id in "${EXPECTED_PROJECT_IDS[@]}"; do
  PROJECT_ARGS+=(--expected-project-id "$project_id")
done

export DRY_RECEIPT="$RECEIPT_ROOT/dry-run.json"
uv run python scripts/remediate_staging_alembic_checksums.py \
  --database-url-file "$DATABASE_URL_FILE" \
  --backup-dir "$BACKUP_DIR" \
  --backup-keyring-file "$BACKUP_KEYRING_FILE" \
  --restore-receipt "$RESTORE_RECEIPT" \
  --receipt "$DRY_RECEIPT" \
  --expected-environment staging \
  --expected-database-name geo \
  --expected-database-user geo_installer \
  --expected-system-identifier "$EXPECTED_SYSTEM_IDENTIFIER" \
  "${PROJECT_ARGS[@]}"
```

接受条件：退出码为 0；收据是 mode `0600` 的 canonical JSON；`mode=dry_run`、
`state=committed`、`updated_rows=0`；`receipt_sha256` 和 `frozen_plan_sha256` 有效。冻结计划精确
包含 source file digests、完整 schema fingerprint、目标的哈希身份、v6 backup/restore
lineage、旧 ledger digest 和三条 old-to-new transition。此后源码、备份、恢复收据、目标身份或
schema 任一变化都必须重新开始，不能继续 apply。

## 4. 只消费该干跑收据执行一次

使用新的 apply 收据路径：

```bash
export APPLY_RECEIPT="$RECEIPT_ROOT/apply.json"
uv run python scripts/remediate_staging_alembic_checksums.py \
  --database-url-file "$DATABASE_URL_FILE" \
  --backup-dir "$BACKUP_DIR" \
  --backup-keyring-file "$BACKUP_KEYRING_FILE" \
  --restore-receipt "$RESTORE_RECEIPT" \
  --receipt "$APPLY_RECEIPT" \
  --dry-run-receipt "$DRY_RECEIPT" \
  --expected-environment staging \
  --expected-database-name geo \
  --expected-database-user geo_installer \
  --expected-system-identifier "$EXPECTED_SYSTEM_IDENTIFIER" \
  "${PROJECT_ARGS[@]}" \
  --apply
```

工具在连接数据库前以 `O_EXCL` 创建 mode `0600` 的 pending 收据并 fsync。事务取得 advisory
lock，并对 Alembic 表及受合同保护的 Dify 关系取锁；更新使用 revision + 两个旧 hash 做 CAS，
必须一次 `RETURNING` 恰好三行。提交前重新检查完整 schema 和 canonical ledger。数据库提交后，
pending 收据才通过 fsync + atomic replace 变成 committed。

正常接受条件：`mode=applied`、`state=committed`、`updated_rows=3`、
`recovered_after_unknown_commit=false`，且 `dry_run_receipt_sha256` 匹配干跑收据。

## 5. 未知提交与恢复

若 apply 在数据库提交附近断线、进程退出或最终收据写入失败，**不要删除或改名 pending 收据，
不要换新路径，也不要手工改 ledger**。使用完全相同的代码、参数、干跑收据、备份、恢复收据和
`APPLY_RECEIPT` 路径重跑第 4 步：

- ledger 仍是精确旧值：工具重新执行受 CAS 保护的三行事务；
- ledger 已是精确 canonical 值：工具不再更新，只完成验证并把收据提交为
  `recovered_after_unknown_commit=true`；
- pending 意图不同、ledger 混合、schema/源码/身份变化：工具拒绝，保留现场调查。

一个已经 committed 的路径不能重用。没有匹配的 pre-existing pending 收据时，canonical
ledger 也不会被当作本次操作成功。

## 6. Alembic 校验、升级与恢复服务

先让正常 Alembic checksum gate 验证 0095；不要 stamp，也不要绕过
`infra/db/alembic/checksums.py`：

```bash
GEO_DATABASE_URL_FILE="$DATABASE_URL_FILE" uv run alembic current
```

只有它无 drift 且明确报告 `0095_synthetic_dify_closed_loop` 时，才用同一个 installer URL 正常
升级当前已审核的仓库 head：

```bash
GEO_DATABASE_URL_FILE="$DATABASE_URL_FILE" uv run alembic upgrade head
GEO_DATABASE_URL_FILE="$DATABASE_URL_FILE" uv run alembic current
```

重建而非直接复用旧应用镜像，确认 migrate 成功后再启动写入者；执行 API readiness、关键写入
canary、Worker/Outbox 处理及 Dify workflow 结果回读。最后把 backup ID、restore receipt hash、
dry/apply receipt hash、部署 commit 和验证结果写入变更记录，不写 secret 或 raw system
identifier。

## 拒绝与处置

- `out-of-band staging scope`：目标不是部署清单中的数据库或 Project 集合；停止，不要改预期值
  迁就目标。
- `authenticated committed backup` / `isolated restore receipt`：备份或空恢复证据不合格；重新
  完成第 1、2 步，不能使用普通文件替代。
- `reviewed destination hash pair changed`：当前源码不是已复核版本；回到 code review。
- `schema fingerprint is not canonical`：实际 0095 schema 有漂移；通过独立迁移修复，不能只改
  ledger。
- `does not match dry-run`：干跑后发生了变化；废弃本次 apply 路径，重新备份、恢复并干跑。
- `did not update exactly the three`：事务已回滚；检查并发操作者和 ledger，不要放宽 CAS。
- PostgreSQL 错误且 apply 收据仍为 pending：按第 5 步以完全相同命令恢复，不要盲目创建新
  收据。

公开收据只包含 hash、revision、database/user、Project UUID 和 system identifier 的 SHA-256；
不包含数据库 URL、密码、raw system identifier、业务行或凭据。
