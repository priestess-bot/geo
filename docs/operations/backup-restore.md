# 认证加密备份与恢复

当前备份覆盖 PostgreSQL 与五个受控 MinIO bucket：`geo-artifacts`、
`geo-restricted-recommendation-artifacts`、`geo-restricted-workflow-c-artifacts`、
`geo-synthetic-style-raw` 和 `geo-synthetic-style-derived`。后两个分别保存 Synthetic/Style
原始加密工件与匿名派生工件，必须独立镜像、独立计数和独立恢复挂载；不得以同一通用 bucket 或
“合计对象数”替代逐桶证明。它用于灾难恢复和升级前回退，
不提供 PITR，也不承诺尚未经过容量演练的 RPO/RTO。默认保留 7 天日备和 28 天周备。

## 1. 七个独立密钥域

生产环境必须配置以下互不相同的文件：

- `GEO_BACKUP_KEYRING_FILE`：只用于数据备份 envelope 和 manifest 签名；不得挂载给应用容器。
- `GEO_SECRET_STORE_MASTER_KEYRING_FILE`：用于业务凭据 envelope，挂载给 Internal API、Worker
  和一次性恢复 probe。
- `GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE`：用于 Secret Store 幂等请求 HMAC，只挂载给
  Internal API 和 Worker。
- `GEO_PROVIDER_ARTIFACT_KEYRING_FILE`：只用于 Provider response artifact 的独立 DEK
  wrapping，只挂通用 Task Worker。
- `GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE`：只用于 Synthetic/Style raw artifact 加密，挂给
  Style Browser Worker、通用 Task Worker（仅处理已冻结的 Synthetic child-model task artifact）
  和一次性恢复 probe。Synthetic retention deleter Worker 不得挂载该 keyring。
- `GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE`：只用于 Recommendation child-task artifact 的
  独立 DEK wrapping，只挂通用 Task Worker 和一次性恢复 probe。
- `GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE`：只用于 Workflow C restricted manual-evidence 的
  独立 DEK wrapping，只挂 Internal API、通用 Task Worker 和一次性恢复 probe。maintenance
  deleter Worker 不获得 keyring；它只在数据库持久化受 lease/fencing 保护的 DEK crypto-erasure
  收据后删除远端对象。

七个文件均必须为普通文件、mode `0600`、不可为 symlink。preflight 会硬性要求备份 keyring
owner 为 root 或当前受控操作者，并要求 Secret Store master keyring 与 request-HMAC 文件的
owner/group 均为 API 镜像身份 `10001:10001`；四个 Artifact keyring 同样必须为
`10001:10001`。隔离恢复数据库密码文件也必须为 `10001:10001`、mode `0600`，使非 root 的
一次性五应用域 probe 能读取；它不属于 key domain，且不得与任一 key material 相同。preflight
还拒绝七个域之间的相同 path、hardlink inode、相同文件内容或任一
重复的解析后 key material。备份 keyring 不得
位于 `GEO_BACKUP_ROOT` 内，也不得与 Secret Store keyring、请求 HMAC key 或备份介质共用
文件。数据备份、备份 keyring、Secret Store/Provider Artifact/Synthetic Artifact/
Recommendation Artifact/Workflow C Artifact 历史 keyring/escrow 至少分属不同存储和保管人。
本地 Compose 的 file-backed secret 是只读 bind mount；六个应用 key source 文件在宿主
必须由 API 镜像运行 UID/GID `10001:10001` 持有，才能在保持 `0600` 时由各自获授权的 API
或 Worker 读取。备份 keyring 则由执行宿主备份命令的受控账号或 root 持有。preflight 应由可读
全部 source 文件的 root/部署账号执行；不要为了通过挂载而放宽为 `0640/0644`。

备份 keyring 是严格 JSON：

```json
{"active_version":2,"format":"geo-backup-keyring-v1","keys":[{"key":"<32-byte-base64>","status":"decrypt_only","version":1},{"key":"<32-byte-base64>","status":"encrypt_decrypt","version":2}]}
```

只能有一个 `encrypt_decrypt`。轮换时先加入更高版本并把旧版本改为 `decrypt_only`；任何仍在
保留期内的备份引用旧版本时不得删除旧 key。备份恢复演练和保留期清理完成后，才可在双人
复核记录下移除已无引用的历史 key。不得把 keyring 放进备份归档。

Secret Store、Provider Artifact、Recommendation Artifact 与 Workflow C Artifact keyring 分别
使用严格 `geo-master-keyring-v1` JSON，包含
integer `active_version` 与以十进制版本字符串为 key 的 32-byte base64 material。Synthetic
Artifact 使用独立的 `{schema_version:1, active_version:"1", keys:{...}}` 合同，并从 root key
按 Project/tier 做 HKDF；版本同样只能是 canonical 正十进制字符串。同一 keyring 内不得跨版本
复用 material；即使五应用域文件格式不同，文件、inode 和每一份 root key material 仍必须不同。
request-HMAC 文件是单独的 32-byte base64 key，不是上述任一 keyring 的导出值。

## 2. 目录与文件合同

`GEO_BACKUP_ROOT` 必须预先存在、mode `0700`、不可为 symlink。备份脚本维护：

```text
GEO_BACKUP_ROOT/
  daily/<UTC backup id>/
  weekly/<UTC backup id>/
  staging/
  restore-receipts/
```

所有目录为 `0700`，文件为 `0600`。每个已提交备份目录只包含：

```text
postgres.sql.gz.enc
minio.tar.enc
manifest.json
manifest.sig
COMMITTED
```

PostgreSQL gzip 流和 MinIO tar 流分别使用随机 256-bit DEK 做 AES-256-GCM 流式加密。DEK
由当前备份 key 通过 HKDF 派生的 KEK 包装；envelope header 作为 AAD。`manifest.json` 是
canonical JSON。当前 v6 除记录密文 SHA-256/size、source project/table/object 数、project
membership、evidence、monitoring report 三组关键关系计数、migration revision，以及截至该
revision 的全部 Alembic upgrade/down SQL 确定性校验账本外，还认证冻结 source environment、
database/user、PostgreSQL system identifier、完整排序 Project ID 集合，以及数据库内实际
`alembic_sql_checksum_ledger`。repository ledger 与 database ledger 分开保存和计算摘要，允许
恢复端识别“源码已合法更新、数据库账本尚待受控修复”的状态，不能让其中一方冒充另一方。
源码账本逐文件保存路径和 SHA-256，并对 canonical 账本再计算总 SHA-256；恢复端必须用目标
服务器上的仓库重新生成完全相同的账本，不能只凭 `alembic_version` 名称相同即通过。
Secret Store key/secret/distinct-version probe 计数、Provider master-key/active-DEK/
committed-recoverable-artifact 计数、Synthetic master-key/active-DEK/未删除工件/tier-key 工件
计数与两类代表 probe 目标、Recommendation master-key/lineage/代表 probe 计数和来源收据摘要、
以及 Workflow C master-key/active-DEK/recoverable-artifact/代表 probe 计数和来源收据摘要。清单
还保存 `projects`、
`project_memberships`、`evidence_items`、`monitoring_reports` 四张表的确定性 SHA-256：每行
转换为 `jsonb` 文本，按 `C` 排序，通过 PostgreSQL `COPY ... FORMAT text` 流式哈希，不保存
或打印行内容；`manifest.sig` 使用独立 HKDF 派生 key 的
HMAC-SHA-256。`COMMITTED` 最后原子写入，缺失即视为未完成备份。

MinIO 明文只在一次性 `backup-object-store` 容器的 `/plaintext-staging` tmpfs 中形成，脚本
trap 会在成功或失败后删除；宿主 staging 只接收加密流和非敏感计数。PostgreSQL 明文 dump
不落盘。

## 3. 生产备份

先执行配置门禁，再由 cron/systemd timer 调用：

```bash
make production-preflight PROD_ENV=infra/production.env
make backup PROD_ENV=infra/production.env
```

环境身份必须显式传给备份入口。默认值是 `production`；受控 staging 备份必须使用
production-equivalent Compose 与同一套 preflight/恢复合同，并执行：

```bash
BACKUP_SOURCE_ENVIRONMENT=staging make backup \
  PROD_ENV=/secure/path/staging-production-equivalent.env
```

不得对 development Compose 栈使用这个标签，也不得事后修改 manifest 中的 environment、
database identity、Project ID 或 database ledger。v5 备份仍可用于其原有恢复流程，但不能作为
staging checksum remediation 的输入；该操作只接受带完整源身份的 v6 备份。

脚本启用 `bash` pipefail 和 `umask 077`。任一 `pg_dump`、gzip、MinIO mirror/tar、加密、
hash、签名或权限步骤失败时，整个 pending 目录会删除，不会出现 `COMMITTED`。成功后脚本
立即自验 HMAC、密文 hash/size 和 envelope lineage，再把 staging 目录原子移动到 `daily`。
PostgreSQL 计数、四表内容 hash 与 `pg_dump` 全部绑定同一个导出的 repeatable-read snapshot，
在线写入不会让清单与 dump 指向不同数据库时点。
备份与恢复通过 `GEO_BACKUP_ROOT/.backup.lock` 使用同一个非阻塞独占锁；并发任务直接失败，
不会让同秒目录提交、保留期清理或两个固定名称的隔离恢复容器相互覆盖。

将成功输出中的目录记入变更单，但不要记录任何 key、数据库 URL、对象存储凭据、密文 header
或 secret reference 内容。备份目录应复制到具备不可变/离线保护的独立介质；本地保留不等于
满足 3-2-1 策略。

## 4. 隔离恢复验收

宿主必须先建立专用 tmpfs。不能把普通 `/tmp`、磁盘目录或仅在结束时删除的目录作为明文
恢复区：

```bash
sudo install -d -o root -g root -m 0700 /run/geo-restore-tmpfs
sudo mount -t tmpfs -o size=16g,mode=0700,nodev,nosuid,noexec \
  geo-restore-tmpfs /run/geo-restore-tmpfs
```

将该目录写入 `GEO_RESTORE_TMPFS_ROOT`。容量必须覆盖较大的已解密 PostgreSQL gzip 或 MinIO
tar 及对象展开峰值；应按实际数据规模预留余量。preflight 和恢复脚本都会检查绝对路径、
无 symlink、`0700`、可信 owner、可写及实际 filesystem type 为 `tmpfs`，任一不符即停止。

`BACKUP_DIR` 是完整的已提交目录。为兼容旧自动化，变量名 `BACKUP_FILE` 仍可使用，但它也
必须指向目录；旧的明文 `postgres.sql.gz` 不再接受。

```bash
sudo make restore-smoke \
  PROD_ENV=infra/production.env \
  BACKUP_DIR=/srv/geo-backups/daily/<UTC-backup-id>
```

生产恢复必须由受控 root 操作者执行：脚本需要把已验证、位于 tmpfs 的对象副本短暂改为一次性
probe 身份 `10001:10001`，同时仍保持目录 `0700`、文件 `0600` 和只读 bind mount；它不会
放宽为其他宿主用户可读。probe 完成后对象目录、隔离数据库和容器会在回执持久化前删除。

恢复顺序固定如下：

1. 检查目录/文件 owner、`0700/0600`、symlink、完整文件集和 commit marker。
2. 先验 HMAC、canonical manifest、密文 SHA-256/size 和 envelope scope，再解密。
3. GCM tag 验证完成前不向 gzip、psql 或 tar 释放任何明文；临时明文只在 `0700` restore
   staging 中，异常和成功都删除。
4. 在 `restore-smoke-postgres` tmpfs 实例恢复，逐项比对 project 数、public table 数、
   project membership/evidence/monitoring report 关系计数和 migration revision；对目标仓库
   重新计算截至该 head 的 Alembic upgrade/down SQL checksum ledger 并要求逐项一致；对四张
   核心表按同一序列化合同重算 SHA-256，并检查全部 public foreign key。
5. 使用独立恢复库和历史 Secret Store keyring 校验所有非退役 key-version canary；按
   ciphertext 实际引用的每个 master-key version 各解密一条代表 secret，并与备份时冻结的
   distinct version 目标精确一致。没有业务 secret 时 receipt 必须明确记录
   `representative_secret_count=0`，不能写成已验证代表 secret。
6. 安全解包 MinIO tar，拒绝绝对路径、`..`、重复项、symlink、hardlink、device/FIFO；对每个
   对象核验备份内 SHA-256，并与 manifest object count 一致。
7. 一个无 egress 的一次性 `10001:10001` probe 分别使用历史 Provider Artifact、Synthetic
   Artifact、Recommendation Artifact 与 Workflow C Artifact keyring 校验五个应用加密域全部
   在用 key-version canary。Provider 必须认证解密至少一条 committed 工件的实际 wrapped DEK
   与对象；Synthetic 必须分别认证解密一条 independent-DEK restricted 工件和一条 Project/tier-key
   工件；Recommendation 与 Workflow C 都必须认证解密各自的代表真实对象、校验被引用的 DEK
   和来源收据摘要。probe 只能读取第 6 步已做逐对象 hash 验证的五个 tmpfs bucket 副本，并按
   固定 bucket-to-reader allowlist 路由；未知 bucket、跨 bucket URI 或缺少任一恢复挂载必须失败，
   不得回退到通用 object reader。任一域
   或任一 Synthetic 加密分支为零时，production receipt 必须拒绝，不能以“无数据可验证”通过。
8. 先在 tmpfs 形成候选回执；删除隔离容器和整个明文 tmpfs staging 并确认路径消失后，才在
   `restore-receipts/` 原子写入 canonical receipt。receipt 记录四表 hash、逐对象 hash、
   五个应用 keyring 域的逐版本 canary 与零/非零代表 secret/artifact 的真实结果。

该命令不会写生产数据库或生产 MinIO。至少每月执行一次；每次任一应用 keyring、备份
keyring、schema 或恢复镜像升级后必须额外执行。Release Gate 只接受完整 receipt，单独
的命令退出码、gzip/tar 可读或数据库行 hash 不构成可恢复证据。

## 5. 故障处置

以下情况一律 fail closed，先保留非敏感错误码和备份 ID，再调查介质/key 版本，不得跳过：

- `COMMITTED`、manifest 或 signature 缺失/非 canonical/被篡改；
- 密文被截断、SHA-256/size 不符或 AES-GCM tag 错误；
- keyring 缺失目标历史版本、key 错误、格式错误、权限过宽或为 symlink；
- 备份 keyring 与 Secret Store keyring/数据备份路径重合；
- PostgreSQL 数量、migration revision、Alembic SQL checksum ledger、FK，任一 keyring
  canary/代表解密或 MinIO 对象 hash/count
  不一致；
- 恢复清理失败。

不要修改 manifest 来“修复”旧备份，也不要把 key 放入备份目录。若历史 key 已丢失，该备份
不可恢复，应按事故处理，而不是生成例外 receipt。

## 6. Development 完整烟测

development Gate 不允许隐式选择常驻 `geo` 数据库或 `geo-artifacts` bucket。标准入口会从
Alembic graph 动态解析当前 single head，创建唯一 source database 和五个独立 source bucket，
在 tmpfs 生成彼此独立的 Secret Store、Provider Artifact、Synthetic Artifact、Recommendation
Artifact、Workflow C Artifact 历史 keyring，并使用真实领域写入路径准备各域的 canary 与代表
工件：两个 Secret master-key version 和各一条代表 secret、两个 Provider master-key version 与
一个包含 raw/derived ciphertext 的 committed bundle、两个 Synthetic master-key version 以及
independent-DEK 与 Project/tier-key 各一条工件，另加 Recommendation 与 Workflow C 的实际
wrapped-DEK/object lineage。随后自动执行备份、空环境恢复、错误/缺失 key 负测、明文扫描和
临时资源清理：

```bash
make backup-restore-dev-smoke
```

该命令生成与生产相同的五文件认证加密 bundle，并恢复 PostgreSQL、逐表重算四组业务 hash、
逐对象恢复五个 MinIO bucket。随机备份 key 只存在于本次临时目录；恢复后用五份真实应用
keyring 完成联合 probe，并分别用同版本随机错误或缺失的 Secret Store、Provider、Synthetic、
Recommendation 与 Workflow C keyring 证明 fail-closed。恢复副本、明文和 key 删除成功后才写
development receipt；其 `production_equivalent_restore_receipt` 必须已满足同一份 v6 manifest
的全部生产门槛。
Gate 只有在 source/restore database、五个 source/restore bucket 和 tmpfs keyring 全部确认消失后
才成功；磁盘只保留 `artifacts/backup-restore-smoke-authenticated/<run-id>/` 下的认证密文 bundle
与 receipt。底层 `scripts/backup_restore_development_smoke.sh` 仍要求显式传入隔离 source、五个
bucket 和五份应用 keyring，仅供受控诊断，不是标准验收入口。该命令不生成可用于生产恢复的
长期 key escrow，
因此只能作为交付烟测，不能替代生产备份。

## 7. 历史明文烟测处置记录

2026-07-23 清理了旧版 `artifacts/backup-restore-smoke/` 下 5 个未跟踪 run：
`20260715T142620Z`、`20260715T144750Z`、`20260715T145624Z`、
`20260715T150419Z`、`20260717T191933Z`。清理范围合计 32 个文件、文件内容总计
1,301,721 bytes；最高风险类别为磁盘明文数据库/对象恢复工件及宽权限。未在处置记录保存
内容、内容 hash 或对象名。删除后已确认整个旧 generated 目录不存在；回归门禁要求新的
development smoke 只在 tmpfs 形成明文，并且磁盘输出仅允许五文件认证密文 bundle 与安全
receipt。

另有两处早于本合同、由其他验收流程生成的未跟踪明文证据尚未获准删除：

- `artifacts/advinsys-v600/20260716-advinsys-v600-01/backup-restore/20260716T040909Z`
  （13 files，116,090 bytes）；
- `artifacts/advinsys-v600/20260716-gate1-premerge/backup-restore/20260716T051157Z`
  （13 files，116,083 bytes）。

它们按 `PREEXISTING_BACKUP_PLAINTEXT` 聚合披露，不打印对象名、内容或内容 hash。直接运行
`uv run python scripts/scan_backup_plaintext_artifacts.py artifacts` 必须因这两处返回 `3`；
`make scan-backup-plaintext` 只对这两个冻结绝对仓库位置应用
`--allow-disclosed-legacy`，仍会让任意新增目录、明文、软链接、非合同文件或宽权限认证备份
返回非零。删除这两处历史证据需要单独授权；删除后应同时移除脚本中的精确 allowlist。

## 8. 真实验收记录

2026-07-22 在独立新建数据库和临时 MinIO bucket 执行了 development 完整烟测
`20260722T214007Z-1657751`。source database 从空库迁移到 single head
`0030_synthetic_lab`，包含 1 个 Project、1 条 membership、1 条真实 Secret Store 代表
secret、1 个 key-version canary 和 2 个 MinIO 对象。恢复结果逐项确认：

- 148 张 source/restored public tables、Project 数和三组关键关系计数一致，全部 public FK
  通过；四张核心表的确定性 source/restored hash 全部一致；
- 2 个对象逐对象 SHA-256 与数量一致；真实 keyring 可解密 canary 和代表 secret，同版本随机
  错误 key 得到预期认证拒绝；
- 恢复数据库、临时 bucket、容器、Secret key、`/dev/shm` 明文 staging 均已删除后才持久化
  receipt；磁盘只保留 mode `0600` 的五文件认证密文 bundle 与 receipt，目录为 `0700`；
- 对该 run 执行明文扫描为零发现；对全量 `artifacts/` 扫描除上述两处已披露 legacy 目录外
  无其他发现。

该 run 的随机备份 key 已销毁，因此它是交付时的可审计 smoke evidence，不是今后可重复恢复
的灾备介质。它早于 Provider/Synthetic/Recommendation/Workflow C Artifact keyring 分域，
只证明 Secret Store、PostgreSQL 和 MinIO 的阶段性恢复，不能作为当前最终生产恢复 Gate。
生产 Gate 仍必须使用受保管的七个密钥域产生并恢复当期备份，并取得第 4 节全部代表解密证据。
