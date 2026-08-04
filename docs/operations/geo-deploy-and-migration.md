# GEO 单栈部署与迁移手册

本手册把当前功能完整的 `geo-advinsys-staging-v2 + Dify` 作为唯一 GEO
运行栈。`geo-development` 是可删除的开发测试实例；`assetgraph`、`sub2api`
和其他 Compose project 不属于 GEO，本手册不会操作它们。

## 1. 目标服务器要求

目标服务器使用 Linux、Docker Engine、Docker Compose v2、Git、Python 3、OpenSSL、
GPG、`gh` 和 `uv`。GitHub 归档仓库必须是私有仓库；密码只通过权限为 `0600` 的文件提供。
服务器只需内网访问，不要求本项目自带 HTTPS 网关。默认端口保持当前行为：

| 服务 | 端口 |
| --- | ---: |
| Admin Web | 13001 |
| Customer Web | 13000 |
| Internal API | 18000 |
| Customer API | 18001 |
| MinIO API/Console | 19000/19001 |
| Valkey | 16379 |
| Dify Console | 15000 |

数据库、MinIO、Valkey 和 Dify 内部组件不应暴露到公网。需要跨机器访问时，使用防火墙或
现有内网反向代理限制来源；本项目不自动创建 Caddy/Nginx。

## 2. 一键部署

先准备一个只读或 0600 的 DeepSeek key 文件。模型权重不会进入迁移包，目标机首次启动时
会重新拉取镜像和 Dify 依赖。

```bash
git clone https://github.com/priestess-bot/geo.git /srv/geo
cd /srv/geo
export GEO_INSTALL_ROOT=/srv/geo
export GEO_RELEASE_REF=main
export GEO_DEEPSEEK_API_KEY_FILE=/srv/geo-secrets/deepseek_api_key.txt
./deploy/install.sh
```

脚本会：

1. 固定 Git commit 并检查 Docker Compose；
2. 生成 0600 Secret/keyring 和内网告警证书；
3. 创建并启动锁定版本的 Dify；
4. 自动配置 DeepSeek、导入十条 GEO Workflow；
5. 启动唯一 `geo` Compose project 的 API、Worker、Connector、Browser Capture、MinIO、
   PostgreSQL、Valkey 和双 Web；
6. 执行 health、Compose 和旧栈检查。

如果运行中断，错误会指出缺少的文件或服务。补齐输入后重新执行脚本即可；不会删除已有
数据。Dify 的管理员状态写入 `.runtime/geo-dify-state.json`，不得提交 Git。

常用后续命令：

```bash
GEO_STACK_ENV_FILE=/srv/geo/infra/geo-stack.env ./scripts/geo-stack.sh status
GEO_STACK_ENV_FILE=/srv/geo/infra/geo-stack.env ./scripts/geo-stack.sh doctor
GEO_STACK_ENV_FILE=/srv/geo/infra/geo-stack.env ./scripts/geo-stack.sh logs -- internal-api task-worker
```

## 3. 当前服务器导出

导出前允许短暂停机。默认会暂停 GEO 写入服务和 Dify 应用服务，数据库和对象存储保持
运行；导出完成后自动恢复原来运行的服务。

```bash
cd /home/ymm/ym/gz/20260608-geo
export GEO_SYNC_REPO=priestess-bot/geo
export GEO_SYNC_PASSPHRASE_FILE=/absolute/path/to/migration-passphrase
export GEO_SYNC_OUTPUT_ROOT=/srv/geo-migrations
export GEO_STACK_ENV_FILE=artifacts/advinsys-staging-runtime.env
export GEO_MIGRATION_SECRET_ROOT=/home/ymm/ym/gz/20260608-geo/artifacts/staging-secrets
uv run python scripts/geo_sync.py export-baseline-upload \
  --repo "$GEO_SYNC_REPO" \
  --passphrase-file "$GEO_SYNC_PASSPHRASE_FILE" \
  --output-root "$GEO_SYNC_OUTPUT_ROOT" \
  --secret-root "$GEO_MIGRATION_SECRET_ROOT" \
  --source-project geo-advinsys-staging-v2
```

该命令要求当前 Git 工作树干净，并把正在运行的 commit 写入归档清单。默认短暂停止
GEO/Dify 写入，生成基线后恢复服务，再把压缩后的 GPG payload 拆成小于 GitHub 单文件限制
的分片，上传为一个 GitHub Release。命令不会把密码、keyring 或明文 payload 提交到 Git。
基线 manifest 的 `source_role` 必须是 `source`（也允许从已切换的 `primary` 再导出），而增量
导出只接受 `source_environment=production` 且 `source_role=primary`。迁移密码文件必须是
宿主机权限 `0600`；脏工作树只能显式使用 `--allow-dirty`，该包会标记为不可复现。

如果只需要生成本地包而不上传：

```bash
./scripts/geo-stack.sh export \
  --output-root "$GEO_MIGRATION_OUTPUT_ROOT" \
  --encryption-key-file "$GEO_SYNC_PASSPHRASE_FILE" \
  --secret-root "$GEO_MIGRATION_SECRET_ROOT" \
  --source-project geo-advinsys-staging-v2
```

输出目录包含：

- `manifest.json`：来源 project、Dify project、文件大小、sha256、停写标记和加密算法；
- `payload.tar.gz.gpg`：gzip 压缩后使用 GPG AES-256 加密的实际数据；
- `manifest.json` 不含密码、API key 或密钥材料。

迁移包覆盖：

| 数据 | 内容 |
| --- | --- |
| GEO PostgreSQL | `geo` 数据库的 logical custom dump |
| GEO MinIO | 全部 GEO bucket 数据 |
| GEO Valkey | RDB 运行快照；仅用于恢复待唤醒队列，不是真实业务状态 |
| Dify PostgreSQL | `dify` 和 `dify_plugin` 两个数据库 |
| Dify Redis | Redis RDB |
| Dify Weaviate | `/var/lib/weaviate` 数据归档 |
| Dify 文件存储 | `docker/volumes/app/storage` 和 `docker/volumes/plugin_daemon` |
| Dify 状态 | 管理员状态、应用 token 和 Workflow lineage 文件 |
| Secret/keyring | 仅在加密 payload 内保存，恢复后重新检查权限和解密 canary |

导出前可先做无副作用检查：

```bash
uv run python scripts/geo_migrate.py export \
  --output-root /srv/geo-migrations \
  --encryption-key-file "$GEO_MIGRATION_KEY_FILE" \
  --secret-root "$GEO_MIGRATION_SECRET_ROOT" \
  --dify-state-file .runtime/geo-dify-state.json \
  --no-quiesce
```

正式迁移仍应使用默认停写模式；`--no-quiesce` 只适合检查连接和镜像工具是否可用。

## 4. 新服务器导入

新服务器先完成一次一键部署，使目标数据库、MinIO、Valkey、Dify PostgreSQL、Redis 和
Weaviate 容器存在，然后停止业务写入并导入：

```bash
cd /srv/geo
export GEO_STACK_ENV_FILE=/srv/geo/infra/geo-stack.env
export GEO_SYNC_REPO=priestess-bot/geo
export GEO_SYNC_PASSPHRASE_FILE=/srv/geo-secrets/migration-passphrase
export GEO_MIGRATION_SECRET_ROOT=/srv/geo/.secrets
export GEO_SYNC_RELEASE=geo-migration-<archive-id>

uv run python scripts/geo_sync.py import-baseline \
  --repo "$GEO_SYNC_REPO" \
  --release "$GEO_SYNC_RELEASE" \
  --passphrase-file "$GEO_SYNC_PASSPHRASE_FILE" \
  --secret-root "$GEO_MIGRATION_SECRET_ROOT" \
  --target-empty --confirm
```

导入会先检查 manifest 和加密 payload hash，再执行以下动作：

1. 停止目标 API、Worker、Dify 应用及状态存储写入；
2. 恢复三个 PostgreSQL 数据库 dump；
3. 恢复 GEO MinIO、Valkey、Dify Redis、Weaviate 和 Dify 文件存储；
4. 恢复 Dify state、配置和密钥文件；
5. 检查 Alembic revision、PostgreSQL relation 数量、payload 文件 hash 和 Secret Store
   解密 canary；
6. 写出同目录 `restore-receipt.json`，成功后才恢复已停止服务。

默认拒绝非空目标。密码错误、manifest 不匹配、数据库恢复失败或 keyring 不可解密时会
立即停止，不会生成“看起来成功”的 receipt。

导入成功后，新服务器成为唯一 `primary` 写入源。原本机不要继续作为第二个生产写入源；
可以启动为 `test-replica` 做验证，但本机测试数据会在下一次主服务器增量同步时被覆盖。

## 5. 主服务器到本机的增量同步

增量包必须声明父 Release，不能直接按时间戳合并。当前同步器按组件文件 hash 生成变化和删除
清单：未变化的 PostgreSQL dump、MinIO 归档、Dify 文件归档不会重复进入增量包；变化的组件会
作为完整组件快照进入增量包，因此不会漏掉删除或审批状态变化。后续可以在不改变 Release
合同的前提下替换为 WAL/对象版本增量实现。`--parent-package` 必须指向上一次保留的完整
`geo-runtime-*` 导出包；不要把 delta 包当作下一次导出的比较基线。这样主服务器本地始终
保留一份可复核的全量父状态，而 GitHub 传输仍只上传变化组件。

在主服务器生成并上传增量：

```bash
uv run python scripts/geo_sync.py export-incremental-upload \
  --repo "$GEO_SYNC_REPO" \
  --passphrase-file "$GEO_SYNC_PASSPHRASE_FILE" \
  --parent-package /srv/geo-migrations/<previous-release> \
  --parent-release geo-migration-<previous-release> \
  --output-root /srv/geo-migrations \
  --secret-root /srv/geo/.secrets
```

在当前本机覆盖测试副本：

```bash
uv run python scripts/geo_sync.py apply-incremental \
  --repo "$GEO_SYNC_REPO" \
  --release geo-migration-<delta-id> \
  --passphrase-file "$GEO_SYNC_PASSPHRASE_FILE" \
  --package-cache /srv/geo-migrations/cache \
  --secret-root /srv/geo/.secrets \
  --overwrite-test-replica
```

同步器会自动下载父链、校验连续性、在临时目录物化完整状态，再调用测试副本覆盖导入。
它还会校验每个 delta 的 `parent_archive_id` 与实际父 Release 的 `archive_id`，并拒绝不是
`primary` 来源的 delta。缺父 Release、乱序、错误密码、循环父链或未显式指定
`--overwrite-test-replica` 都会失败。
Valkey/Redis 队列不做增量合并，Durable Job 会从 PostgreSQL 状态重新唤醒。

## 6. 清理旧开发栈

确认迁移包的 `manifest.json` 状态为 `verified-export` 后再执行。默认只停容器；删除旧
开发卷必须显式添加 `--delete-volumes`：

```bash
export GEO_MIGRATION_PACKAGE=/srv/geo-migrations/geo-runtime-<timestamp>/manifest.json
GEO_MIGRATION_PACKAGE="$GEO_MIGRATION_PACKAGE" \
  ./scripts/geo-stack.sh cleanup-legacy --confirm --delete-volumes
```

此命令只匹配 `geo-development` 和 `geo-advinsys-staging`。不会匹配 `geo`、`geo-dify`、
`assetgraph`、`sub2api` 或 `geo-workflowc-fresh-migration`。

## 7. 回滚和故障处理

- 安装失败：保留 Git checkout 和日志，修正缺失 Secret/端口后重试。
- 导出失败：脚本会删除未完成目录，并在 finally 中恢复暂停的服务。
- 导入失败：目标服务保持停止或恢复到导入前状态；不要继续对非空目标重试，先清空目标
  volumes 或重新创建 Compose project。
- 导入成功但业务不可用：保留 `restore-receipt.json`，检查 API `/health`、`/ready`、
  Worker heartbeat、Dify `current` Workflow cards 和浏览器端口；不要用重启替代数据验证。
- 回滚：停止目标 `geo`/`geo-dify`，重新导入上一个已验证 package，随后执行 `doctor`。

## 8. 验收清单

- [ ] `scripts/geo-stack.sh config` 成功。
- [ ] `scripts/geo-stack.sh doctor` 不再报告旧 GEO project。
- [ ] Admin、Customer、Dify 三个页面可以访问。
- [ ] GEO PostgreSQL、Dify `dify`、Dify `dify_plugin` 均可查询。
- [ ] MinIO、Redis/Valkey、Weaviate 数据 hash 与 manifest 一致。
- [ ] Dify `app/storage` 和 `plugin_daemon` 文件 hash 与 manifest 一致。
- [ ] Secret Store/keyring 解密 canary 通过。
- [ ] `restore-receipt.json` 状态为 `verified-restore`。
- [ ] GitHub Release 为私有仓库，只有加密分片和非敏感清单。
- [ ] 增量 Release 的父归档、变更路径和删除路径可验证。
- [ ] 任意失败信息包含失败位置、影响、是否可重试和下一步动作。
