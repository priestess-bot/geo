# `codex/storage-hardening` 执行计划

## 目标

完整实现设计方案 §22.6 和 `CG-PROD-008`：

- production MinIO root/application/backup/restore/retention 身份分离；
- 全部对象存储消费者使用同一非默认 application 配置；
- bootstrap 独占建桶、创建 principal/policy、versioning 和 lifecycle；
- production runtime 禁止自动建桶；
- backup smoke 使用隔离 prefix，不删除业务对象或正式备份；
- 验证基础设施加密卷 receipt 和 encrypted snapshot restore receipt；
- 生成 `tmp/production-object-store-credentials/latest.json`。

## 当前已知缺口

- production overlay 只覆盖 API 的 application credential。
- MinIO 和其他 consumer 仍继承 `minio/minio123`。
- `S3CompatibleObjectStore.ensure_bucket()` 无条件发送 `PUT Bucket`。
- `backup-object-smoke` 使用 root、执行 `mc mb`、删除 source 对象。
- 尚无 bootstrap、最小权限 policy、consumer inventory 和真实加密 receipt Gate。

## 文件所有权

可修改：

```text
infra/docker-compose.production.yml
infra/docker-compose.yml                       # 仅 MinIO/object-store/backup 相关段
infra/minio/**                                 # 新增 bootstrap/policy
infra/object-store.production.env.example      # 新增，不含真 secret
packages/geno_core/geno_core/object_store.py
packages/geno_core/geno_core/runtime.py         # 仅 object-store builder/diagnostic
scripts/verify_backup_smoke.py
scripts/verify_production_object_store.py       # 新增
scripts/run_production_object_store_smoke.py    # 按需新增
tests/test_production_object_store_contracts.py # 新增
tests/test_infra_contracts.py                   # 仅 object-store/Compose 测试区
```

禁止修改：

- 任何数据库 migration；
- Knowledge/Collection lease 实现；
- Admin/Customer/Auth API；
- Compose 中 worker 的 lease/heartbeat/queue command；
- `Makefile`、总 Gate 脚本和总 Gate 测试；
- 设计方案和其他 worktree plan。

## 实施步骤

### 1. 禁止 production 自动建桶

- 为 object-store client 增加显式 `auto_create_bucket`。
- `OBJECT_STORE_AUTO_CREATE_BUCKET=1` 只保留本地开发兼容；production overlay 固定为 `0`。
- 禁止自动创建时做签名 `HEAD Bucket`；不存在或无权时 fail closed。
- 非法布尔配置必须报错，不默认回退。
- 测试证明 production `put_object()` 之前没有 `PUT Bucket`。

### 2. Production MinIO bootstrap

- root credential 只进入 `minio` 和一次性 `minio-bootstrap`。
- 凭据使用 Compose external secrets/受控 secret file 和 `_FILE` 加载，不把原值展开进 `docker compose config` artifact。
- bootstrap 幂等创建 `geno-reports/geno-backups`、application/backup principal 和版本化 policy。
- 配置 versioning/lifecycle，输出不含 secret 的 receipt。
- application/backup 都禁止 admin/CreateBucket。
- restore/retention 是临时身份，完成后撤销。

### 3. Consumer inventory

以下 runtime consumer 必须获得同一 application credential fingerprint：

```text
api
collector-worker
collector-worker-litellm
browser-fidelity-scheduler
report-export-worker
knowledge-worker
task-worker-runtime
task-worker-knowledge
runtime-e2e
```

`backup-object-smoke` 使用 backup 身份。Admin/Customer/Dashboard Web、PDF renderer、Embedding API、recovery dispatcher 和 notification worker 不得获得对象存储 secret。

新增 `build_object_store_from_env` 调用者时，verifier 必须能检测 consumer inventory 漂移。

### 4. Backup/restore smoke

- 不再执行 `mc mb`。
- source `geno-reports` 对 backup 身份只读。
- 正式 `OBJECT_STORE_BACKUP_PREFIX=production/{environment}/` 只允许 put/list/get，禁止 delete。
- `OBJECT_STORE_BACKUP_SMOKE_PREFIX=smoke/{run_id}/` 只允许本次 run put/list/get/delete，跨 run 删除必须拒绝。
- restore 只能写 `geno-reports/restore-smoke/{run_id}/`。
- 不删除原业务对象。
- source、backup、restored 内容的 SHA-256 必须一致。
- 负向测试覆盖 CreateBucket、application delete、backup 写 source、backup 删正式/跨 run prefix。

### 5. Production verifier

Verifier 解析所有 profile 的 merged Compose：

```bash
docker compose --profile "*" \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.production.yml \
  config --format json
```

必须检查：

- 缺任一 required secret 时 config/preflight 失败；
- production merged config 不包含开发默认凭据；
- consumer inventory 精确且 non-consumer 无 secret；
- runtime consumer 全部 `OBJECT_STORE_AUTO_CREATE_BUCKET=0`；
- root/application/backup/restore/retention 不混用；
- runtime 等待 bootstrap 成功再 ready/领任务；
- live put/get/head/hash、policy negative 和 backup/restore 通过；
- receipt、日志和 artifact 的 raw secret count 为 0。

### 6. 加密卷 Gate

- 不用 Compose 字符串冒充加密证明。
- receipt 至少校验 `volume_id/provider/encryption_enabled/key_alias/policy_version/rotation_owner/verified_at`。
- encrypted snapshot restore receipt 至少包含 snapshot ID、新节点/新 volume ID、恢复对象 hash 和验证时间。
- 单元测试可使用 fixture，正式 artifact 缺真实 receipt 时必须失败。

## 测试

```bash
PYTHONPATH=packages/geno_core:apps/api \
  python3 -m unittest tests.test_production_object_store_contracts

PYTHONPATH=packages/geno_core:apps/api \
  python3 -m unittest tests.test_infra_contracts

python3 -m ruff check \
  packages/geno_core/geno_core/object_store.py \
  packages/geno_core/geno_core/runtime.py \
  scripts/verify_backup_smoke.py \
  scripts/verify_production_object_store.py \
  tests/test_production_object_store_contracts.py

python3 -m compileall packages/geno_core/geno_core scripts tests
python3 scripts/verify_backup_smoke.py
python3 scripts/verify_production_object_store.py --config-only
git diff --check
```

具备 Docker 和真实加密 receipt 后执行 merged Compose live smoke。测试凭据必须随机生成并放入临时 secret file，不提交、不打印。

## 验收产物

`tmp/production-object-store-credentials/latest.json` 至少包含：

- schema version、commit SHA、merged Compose hash；
- consumer inventory 和 credential fingerprint；
- bootstrap policy/versioning/lifecycle receipt hash；
- 各 consumer roundtrip；
- policy negative 结果；
- backup/restore 三方 SHA-256；
- encryption/snapshot restore receipt hash；
- `secret_leak_count=0`。

产物不提交，不得包含 access key、secret key、root credential 或可恢复值。

## 提交与 Handoff

建议提交：

```text
feat(storage): disable production bucket auto-creation
feat(storage): provision scoped MinIO production identities
test(storage): add production object-store and restore gate
```

新增并提交 `docs/worktree-results/storage-hardening.md`。明确列出集成 session 需要完成的 Makefile/总 Gate 接线，以及 lease/auth 环境变量应如何并入已收口的 production overlay。

