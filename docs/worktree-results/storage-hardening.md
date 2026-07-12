# storage-hardening handoff

## 状态

`codex/storage-hardening` 已完成对象存储客户端、MinIO bootstrap、身份/policy、production Compose、backup/restore smoke 和专属 verifier。配置合同、单元测试、既有基础设施合同，以及使用随机非默认凭据的隔离 MinIO policy smoke 均通过。

本分支不宣称 Production Final Gate 已通过。九个实际 runtime service 镜像已分别通过 Compose 启动，并在各自容器内使用 native `build_object_store_from_env()` 完成独立 put/head/get/hash。当前唯一未满足的生产证据是平台签发的真实加密卷 receipt，以及从加密 snapshot 恢复到新节点/新 volume 的 receipt。因此未生成 `tmp/production-object-store-credentials/latest.json`；正式 verifier 对缺失 receipt 保持 fail closed。

## 提交

代码提交（基线 `44729afe6e232ae68725cd77752018ed22ec8959` 之后）：

- `ac1b30d` `feat(storage): disable production bucket auto-creation`
- `ecad8be` `chore(storage): keep runtime changes object-store scoped`
- `7c6d65a` `feat(storage): provision scoped MinIO production identities`
- `8f0e191` `fix(storage): require native per-service roundtrip evidence`
- `d86db3e` `fix(storage): remove native smoke volumes`

本文件由后续 handoff commit 提交；最终 branch tip 以集成 session 读取到的 `codex/storage-hardening` HEAD 为准。

## 改动文件

- `packages/geno_core/geno_core/object_store.py`
- `packages/geno_core/geno_core/runtime.py`
- `infra/docker-compose.yml`
- `infra/docker-compose.production.yml`
- `infra/object-store.production.env.example`
- `infra/minio/bootstrap.sh`
- `infra/minio/application-roundtrip-smoke.sh`
- `infra/minio/backup-restore-smoke.sh`
- `infra/minio/reports-lifecycle.json`
- `infra/minio/backups-lifecycle.json`
- `scripts/verify_backup_smoke.py`
- `scripts/verify_production_object_store.py`
- `scripts/run_production_object_store_smoke.py`
- `tests/test_production_object_store_contracts.py`
- `docs/worktree-results/storage-hardening.md`

## 运行合同

- `S3CompatibleObjectStore(auto_create_bucket=True)` 保留本地兼容行为。
- `OBJECT_STORE_AUTO_CREATE_BUCKET=0` 时，首次写入前只执行签名 `HEAD Bucket`；404/403 等状态立即失败，不发送 `PUT Bucket`。
- `OBJECT_STORE_ACCESS_KEY_FILE` / `OBJECT_STORE_SECRET_KEY_FILE` 支持 Compose Secret；同一值的 direct env 与 `_FILE` 同时存在、空文件、不可读文件或非法 boolean 均失败。
- production 的九个 application consumer 固定为：`api`、`collector-worker`、`collector-worker-litellm`、`browser-fidelity-scheduler`、`report-export-worker`、`knowledge-worker`、`task-worker-runtime`、`task-worker-knowledge`、`runtime-e2e`。
- 九个 consumer 使用相同 endpoint/bucket/region 和相同 application Secret file，全部设置 auto-create `0`，并等待 `minio-bootstrap` 成功退出。
- policy-only MC probe 只生成 `production-object-store-shared-identity-roundtrip-v1`，scope 固定为 `shared_identity_policy_only`，不包含或冒充 consumer pass。
- full runner build 当前源码，并对九个 Compose service 分别执行 `docker compose run`；每个容器内使用 native builder、独立 key、`_FILE` credential 完成 put/head/get/hash。
- root Secret 只挂载到 `minio` 和 `minio-bootstrap`。`backup-object-smoke` 只挂载 backup/restore Secret；Web、renderer、embedding、recovery dispatcher 和 notification worker 无对象存储 Secret。
- production `minio_data` 必须是预先创建的 external encrypted volume；Compose 字符串本身不构成加密证明。

## MinIO policy 合同

- bootstrap 独占创建 `geno-reports` / `geno-backups`，启用 versioning、导入 lifecycle、创建用户与 versioned policy，并写无 Secret 的 `bootstrap.json`。
- application 仅可 list/head/get/put `geno-reports`；delete、CreateBucket、admin 和访问 backup bucket 均有 live negative check。
- backup 可读 source；正式 `production/<environment>/` 可 put/list/get 不可 delete；当次 `smoke/<run_id>/` 可 put/list/get/delete；跨 run delete 被拒绝。
- restore 只能读批准 backup prefix 并写/delete 当次 `restore-smoke/<run_id>/`；跨 run 写入被拒绝。
- retention policy 只允许批准 prefix 的删除。restore/retention 用户由 smoke 临时创建，结束后删除，并以再次访问失败生成 `ephemeral-cleanup.json`。
- backup smoke 不执行 `mc mb`、不删除 source，对 source/formal backup/smoke backup/restored 内容校验同一 SHA-256。

## 环境变量与 Secret

production overlay 要求以下 host-side Secret file path 变量，文件内容不会展开到 merged Compose：

```text
GENO_MINIO_ROOT_USER_SECRET_FILE
GENO_MINIO_ROOT_PASSWORD_SECRET_FILE
GENO_OBJECT_STORE_APPLICATION_ACCESS_KEY_SECRET_FILE
GENO_OBJECT_STORE_APPLICATION_SECRET_KEY_SECRET_FILE
GENO_OBJECT_STORE_BACKUP_ACCESS_KEY_SECRET_FILE
GENO_OBJECT_STORE_BACKUP_SECRET_KEY_SECRET_FILE
GENO_OBJECT_STORE_RESTORE_ACCESS_KEY_SECRET_FILE
GENO_OBJECT_STORE_RESTORE_SECRET_KEY_SECRET_FILE
GENO_OBJECT_STORE_RETENTION_ACCESS_KEY_SECRET_FILE
GENO_OBJECT_STORE_RETENTION_SECRET_KEY_SECRET_FILE
```

正式 verifier 还要求这些文件位于仓库外、不是 symlink、mode 为 `0400`/`0600`、内容非默认且五类 access identity 互不相同；全部 credential value 禁止复用。

其他必需配置：

```text
GENO_MINIO_ENCRYPTED_VOLUME_NAME
OBJECT_STORE_BACKUP_PREFIX=production/<environment>/
OBJECT_STORE_BACKUP_SMOKE_PREFIX=smoke/<run_id>/
OBJECT_STORE_RESTORE_PREFIX=restore-smoke/<run_id>/
OBJECT_STORE_RETENTION_PREFIX=retention-approved/<manifest_id>/
MINIO_BOOTSTRAP_ENABLE_EPHEMERAL=0|1
```

## Receipt 与 artifact 合同

- 加密卷 receipt 必须含 `volume_id/provider/encryption_enabled=true/key_alias/policy_version/rotation_owner/recovery_owner/verified_at`。
- snapshot restore receipt 必须含 `snapshot_id/source_volume_id/new_node_id/new_volume_id/restored_object_hash/verified_at`，且新旧 volume ID 不同、hash 为 SHA-256。
- full verifier 还消费 bootstrap、backup/restore、native consumer roundtrip 与 ephemeral cleanup receipt。consumer receipt 必须是 `compose_service_native_builder` scope，并提供九个独立 container ID、逐 service binding、native builder execution path、`_FILE` source、auto-create=false 和统一 fingerprint；shared-identity receipt 会被明确拒绝。
- 最终 `production-object-store-credentials/latest.json` 包含 git commit/dirty、merged Compose hash、consumer inventory、不可逆 application access-key fingerprint、policy/receipt hash、roundtrip、negative results、三方 restore hash、加密 receipt hash和 `secret_leak_count=0`，不包含可恢复 credential。

## 已执行测试

通过：

```text
PYTHONPATH=packages/geno_core:apps/api python3 -m unittest tests.test_production_object_store_contracts
13 tests, OK

PYTHONPATH=packages/geno_core:apps/api python3 -m unittest tests.test_infra_contracts
20 tests, OK

PYTHONPATH=packages/geno_core:apps/api python3 -m unittest <8 个 object-store/runtime focused core tests>
8 tests, OK

PYTHONPATH=packages/geno_core:apps/api python3 -m unittest tests.test_report_export_worker_contracts
3 tests, OK

python3 scripts/verify_backup_smoke.py
15 checks, pass

python3 scripts/verify_production_object_store.py --config-only
pass；全部 profile merged Compose、caller inventory、consumer/non-consumer Secret、bootstrap dependency 通过

python3 -m ruff check <任务书文件 + runner>
pass

python3 -m compileall -q packages/geno_core/geno_core scripts tests
pass

sh -n infra/minio/bootstrap.sh infra/minio/backup-restore-smoke.sh infra/minio/application-roundtrip-smoke.sh
pass

git diff --check
pass
```

隔离 live policy smoke：

```text
python3 scripts/run_production_object_store_smoke.py \
  --policy-only \
  --native-consumers \
  --project-name geo-storage-hardening-native
```

结果：pass；run ID `03f401f9-306b-411f-a06b-8d3fc5490a4c`；随机 Secret file、动态专用 host ports、独立 Compose project/volume；结束后 container/network/volume 和临时 Secret 均清理。验证了非默认 `_FILE` root/app/backup/restore/retention、versioning/lifecycle、application/backup/restore negative、正式与 smoke prefix、三方 hash、临时身份撤销及 raw Secret count 0。九个 Compose service 均 build 当前源码，并在九个不同 container ID 内通过 native builder roundtrip；receipt 中 service count=9、container count=9、fingerprint count=1、credential source=`OBJECT_STORE_ACCESS_KEY_FILE`、auto-create 全部为 false。

未提交的无 Secret receipt 位于：

```text
tmp/production-object-store-smoke/03f401f9-306b-411f-a06b-8d3fc5490a4c/
```

扩大执行 `tests.test_core_contracts` 时共运行 279 tests，出现 10 failure + 1 error；失败均在未改动的 notification/repository `psycopg.types.json.Jsonb` 字符串表示断言及既有 float 精确相等断言。上述八个与本改动直接相关的 core tests 单独全部通过。

## 未完成的 live Gate / 外部 blocker

1. 环境中没有真实 encrypted volume receipt，也没有 encrypted snapshot 在新节点/新 volume 的 restore receipt；因此 full verifier 未运行，正式 `latest.json` 未生成。
2. 没有运行包含 PostgreSQL/Qdrant/heavy model 的全栈 Production Final Gate；这属于 integration 分支职责。

## 集成分支动作

1. 合并本分支后，以 storage overlay 为 Compose 真源；加入 lease/auth 环境变量时保留 external Secret、`_FILE`、consumer anchor 和 `minio-bootstrap` dependency。
2. 在 `Makefile` 增加 config-only 与 full object-store Gate 入口，并接入 `scripts/verify_production_v1_gate.py`；本分支按任务边界未修改这两个文件。
3. 在目标平台创建 encrypted external volume，提供两类真实 receipt；用当前合并 commit 重跑 full runner/verifier。
4. 在最终 merge commit 上重跑 `--native-consumers`；不要复用本分支 commit 的 service receipt，也不要把 shared-identity policy-only receipt 提升为 production 证明。
5. 确认 full artifact 绑定最终 merge commit、`worktree_dirty=false`、`secret_leak_count=0`，再允许 Production Final Gate Green。
6. Compose 冲突解决后重跑所有 profile 的 merged-config verifier；新增 `build_object_store_from_env()` 调用文件会触发 caller inventory drift，必须映射到明确服务。

## 回滚注意

- 回滚只能轮换到另一组受控非默认 credential，不能恢复 `minio/minio123`。
- 保留 external encrypted volume、bucket versioning、lifecycle 和 additive receipt；不要删除既有 artifact。
- application/backup policy 收紧失败时 fail closed，禁止临时授予 root 或 CreateBucket 绕过。
- restore/retention 失败后仍须执行治理 cleanup 并验证 principal 已撤销。
