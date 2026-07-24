# 生产部署手册

## 1. 准备镜像与 Secret

复制 `infra/production.env.example` 为部署机外部配置 `infra/production.env`，将所有
`@sha256:replace` 替换为实际 digest。应用、安装、通用 Worker、Style Browser 数据库身份，
通用/Style Object Store 身份和备份身份必须相互独立。以下七个密钥域使用不同文件和不同
256-bit key material：

- `GEO_BACKUP_KEYRING_FILE`：数据备份 envelope；
- `GEO_SECRET_STORE_MASTER_KEYRING_FILE`：Connector/Provider/登录凭据；
- `GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE`：Secret command 幂等 HMAC；
- `GEO_PROVIDER_ARTIFACT_KEYRING_FILE`：Provider response artifact DEK wrapping；
- `GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE`：Synthetic/Style raw artifact encryption；
- `GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE`：Recommendation child-task artifact DEK wrapping；
- `GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE`：Workflow C restricted manual-evidence DEK wrapping。

文件改名、硬链接、复制同一内容或把相同 key material 重新排版成另一份 JSON 都不能构成
隔离。preflight 分别检查 path、inode、内容与解析后的 key material，任一复用即停止；所有
keyring 都不得位于 `GEO_BACKUP_ROOT`、恢复 tmpfs 或彼此的历史 escrow 存储域。

Compose file-backed secret 会保留宿主 owner/mode。API 镜像以 `10001:10001` 运行，因此
Secret Store、Provider Artifact、Synthetic Artifact、Recommendation Artifact、Workflow C Artifact
keyring 和 request-HMAC source 必须 `chown 10001:10001` 且 `chmod 0600`；Style Browser 的专用
数据库/Object Store Secret 也必须由运行身份 `10001:10001` 可读且不得向其他服务复用。
`GEO_RESTORE_SMOKE_PASSWORD_FILE`
同样由一次性非 root probe 使用，必须 `10001:10001`、`0600`，但它不是 key domain。
备份 keyring 由宿主备份操作者/root 持有且不挂载容器。上述 owner/group 是 preflight
硬门禁，不只是文档约定。使用能读取全部 source 的受控部署账号（通常为 root）执行
preflight，禁止以 `0640/0644` 绕过 UID 映射。

将已审核的 `infra/style-adapter-registry.v1.json` 部署到
`GEO_STYLE_ADAPTER_REGISTRY_FILE` 指向的绝对宿主路径，owner 为 root/受控部署账号、mode
`0444`。`GEO_STYLE_ADAPTER_REGISTRY_SHA256` 必须等于该文件逐 byte SHA-256；Compose 只读挂到
`/etc/geo/style-adapter-registry.json`。registry 只允许九个冻结 channel 和严格 adapter release
字段；每个 release 的 `allowed_resource_hosts` 与任务冻结的 document/redirect hosts 合并后，
必须是 `GEO_STYLE_ALLOWED_EGRESS_HOSTS` 的子集，否则 Worker 中止请求。首版包含九渠道
`public-v1` 和一个经审核但不含凭据的 Reddit `authenticated-v1` selector flow；加入或改变登录
selector、内容 selector、资源 host、timeout 或 release 必须重新进行合规审核并更新 digest，
登录凭据本身只能保存为 Secret Reference。每个 release 冻结 `reviewed_fixture` 或
`live_canary_approved`；checked-in 首版全部为前者。Authenticated live enqueue 只接受
`live_canary_approved`。该登录 release 在当前自动化出口的无凭据 canary
触发 Reddit JS challenge，未绕过且未取得可用 DOM；因此只有在获授权账号和正常网络中另行
完成 live canary 后才可批准启用，challenge/验证码路径必须保持 `blocked` 且不产生样本。

在宿主创建独立 `tmpfs` 挂载并以 `0700` 保护，将路径配置为
`GEO_RESTORE_TMPFS_ROOT`；普通 `/tmp` 或磁盘目录不能用于恢复明文。推荐挂载命令、容量估算及
持久化 mount unit 见 [认证加密备份与恢复](backup-restore.md)。

生产配置禁止使用源码 build、宿主源码挂载、默认密码、公开 PostgreSQL/MinIO/Valkey 端口或 Dev Tools。

Admin Web 不兑换客户邀请。`GEO_ADMIN_OIDC_LOGIN_URL` 和
`GEO_ADMIN_OIDC_LOGOUT_URL` 必须指向受信任边缘网关的 HTTPS 入口，origin
必须精确列入 `GEO_ADMIN_OIDC_ALLOWED_ORIGINS`。边缘网关负责 Authorization Code +
PKCE、state/nonce 和会话；它必须删除浏览器自带的 `Authorization`，只把验证后映射的
Bearer 身份转发给 Admin Web。Admin Web 再将该 Bearer 原样转发到 Internal API，由 API
复核 issuer、audience、签名和项目角色。Customer Web 只能使用 API 签发的 Customer
Session Cookie，两个信任域不可互换。

## 2. 校验配置

```bash
make production-config PROD_ENV=infra/production.env
```

该入口先运行安全 preflight，再渲染 Compose。preflight 会阻断缺失或空 Secret 文件、
权限不是要求的 `0400/0600`（七个 key 文件严格为 `0600`）的 Secret、symlink/key owner
不匹配、keyring/HMAC 格式或路径隔离错误、密钥 path/inode/内容/material 复用、非 `0700`
备份根、非 `tmpfs` 的恢复明文根、Style image 未固定 digest、Style Chromium 路径、
composition factory、registry 文件/摘要/schema 或精确 egress hostname allowlist 非法、非
HTTPS OIDC/公开 URL、
无效 Release 版本和运行阈值；错误只输出稳定错误码和配置项名，不输出配置值或
Secret 内容。不要绕过该入口直接启动生产栈。

确认常驻业务服务包含 `internal-api`、`customer-api`、`task-worker`、隔离的
`style-browser-worker`、`workflow-c-maintenance-scheduler`、`workflow-c-maintenance-worker`、
`outbox-relay`、`admin-web`、`customer-web`、PostgreSQL、MinIO 和 Valkey，并且 `migrate`、
`minio-bootstrap` 是受控一次性服务。不得出现 Qdrant、LiteLLM、旧 Dashboard、旧 Web、历史
Worker或虚假的 Prometheus scrape target。Prometheus/Grafana 当前阶段未启用。

生产网络中只有 Internal API、Task Worker 和 Style Browser Worker 同时加入 `backend` 与
`egress`；Customer
API、Relay、PostgreSQL、MinIO 和 Valkey 只能加入内部 `backend`。Customer API 只持有
PostgreSQL 和 Session 所需 Secret，不能获得对象存储、Valkey 或模型凭据。

Compose 中每个常驻服务的 CPU/内存上限、API 的 `GEO_DB_POOL_MAX_SIZE=10`、4 个 Task
Worker process、1 个 Style Browser Worker（1 process/1 thread、PID 上限 512）和 1 个 Relay，均由
`benchmarks/roadmap/performance-profile-v1-non-b.json` 冻结并共同构成性能证据身份。任何一项
调整，或 Style adapter registry digest/robots timeout 变化，都必须先批准并发布新
profile/hash，再按新 profile 重跑完整性能与正确性 workload；调整前已有的吞吐、延迟和队列
结果只能用于诊断，不得继续作为 Release Gate 的通过证据。

性能结果必须按 workload 中冻结的四个 Sampling Run 和九个 Style Channel 分别记录明细。
每个 Run 独立满足 1,000 个 planned/terminal Task、100 个同时 eligible 与 dispatch p95；每个
Channel 独立满足 200 个 approved sample、40 个固定 Case、每 Case 4 个候选和三臂各 10 次。
所有汇总计数必须与明细精确相等，任一 Provider、Project 或 Channel 的缺失都不能由其他项
补量后通过。

## 3. 启动

```bash
make production-config PROD_ENV=infra/production.env
docker compose --env-file infra/production.env \
  -f infra/compose.prod.yml -f infra/compose.style-collection.yml pull
make production-up PROD_ENV=infra/production.env
docker compose --env-file infra/production.env \
  -f infra/compose.prod.yml -f infra/compose.style-collection.yml ps
```

`migrate` 与 `minio-bootstrap` 必须成功退出，API、Worker 和 Web 才能进入可用状态。Internal
API、`task-worker` 与 `style-browser-worker` 挂载 Secret Store master keyring 和
request-HMAC key；Customer API、Web、Relay 不得获得它们。Provider Artifact 与 Recommendation
Artifact keyring 只挂 `task-worker`；Synthetic Artifact keyring 挂 `style-browser-worker` 和
`task-worker`，后者只可解密已冻结的 Synthetic child-model task artifact，不持有 Style
Collection 浏览器登录凭据或受限 writer principal。
Workflow C keyring 只挂 Internal API、`task-worker` 和一次性恢复 probe。Internal API 仅有 restricted
bucket writer 凭据，Task Worker 仅有 reader 凭据，专用 `workflow-c-maintenance-worker` 只持有
deleter 凭据、不持有 keyring；它必须先通过 PostgreSQL 中受 lease/fencing 保护的 crypto-erasure
函数持久化 DEK 销毁收据，之后才能删除对象。三类对象存储凭据不可复用，writer/reader 不得删除，
deleter 不得写入或访问 `geo-artifacts`。`workflow-c-maintenance-scheduler` 只持有 Worker
数据库身份：它按固定间隔调用持久化、项目范围的 seed，原子创建/合并 maintenance Durable Job
及 outbox wake；它没有任何 MinIO、keyring 或 broker consumer 凭据。Style Browser
只使用 dedicated Worker 数据库和 Style Object Store 身份，不获得 DeepSeek、Provider Artifact、
Recommendation Artifact、Auth Token 或备份 Secret。`task-worker` 使用通用 Worker/Object Store
身份和 DeepSeek Key；`outbox-relay` 只使用 Worker 数据库身份。备份 keyring 不挂载任何常驻
容器。Admin/Customer Web 只绑定本机回环地址，外部 TLS、域名和访问控制由受管反向代理提供。

`synthetic-artifact-maintenance-worker` 只持有 Worker 数据库身份及 Synthetic raw/derived 两桶的
deleter 凭据，不获得任何 artifact keyring、浏览器登录凭据、writer/reader principal 或 egress。
Relay 按固定间隔调用原子 `geo_enqueue_synthetic_artifact_maintenance`，为每个 Project 创建或唤醒
一个 Durable Job 和对应 outbox；专用 Worker 只在该 Job 的 Project scope 内 stage/claim。它先持久化
crypto-erasure 收据，再删除远端对象；部分删除失败只会进入受 fencing 保护的 retry。

`/health` 只表达 API 进程存活；`/ready` 才检查当前 surface 的必需依赖。Customer 只检查
PostgreSQL，Internal 检查 PostgreSQL、Valkey 和 MinIO。Worker/Relay Compose healthcheck
读取 PostgreSQL heartbeat、Valkey 连接和队列卡滞分类：

```bash
docker compose --env-file infra/production.env -f infra/compose.prod.yml \
  exec internal-api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').status); print(urllib.request.urlopen('http://localhost:8000/ready').status)"
docker compose --env-file infra/production.env -f infra/compose.prod.yml \
  exec customer-api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').status); print(urllib.request.urlopen('http://localhost:8000/ready').status)"
docker compose --env-file infra/production.env -f infra/compose.prod.yml \
  exec task-worker python -m geo_worker.runtime_health heartbeat --service-type task_worker
docker compose --env-file infra/production.env -f infra/compose.prod.yml \
  exec outbox-relay python -m geo_worker.runtime_health heartbeat --service-type outbox_relay
docker compose --env-file infra/production.env \
  -f infra/compose.prod.yml -f infra/compose.style-collection.yml \
  exec style-browser-worker python -m geo_worker.runtime_health \
  heartbeat --service-type style_browser_worker
```

默认 heartbeat 间隔/过期阈值为 10/30 秒，queued/retry 为 600 秒，Outbox 为
300 秒，running/finalizing 为 lease expiry 后 60 秒。命令输出实际阈值、稳定分类及
Project/Job ID，不输出任务正文、错误正文、客户 URL 或凭据；非零退出必须先处理后上线。

## 4. 首次 Owner 初始化

空库迁移完成后，先从 IdP 管理台确认初始管理员 token 中的 `iss`、`sub` 和
tenant claim。填写 `infra/production.env` 的全部 `GEO_BOOTSTRAP_*` 值，其中：

- `GEO_BOOTSTRAP_OIDC_ISSUER` 必须与 `GEO_JWT_ISSUER` 完全一致；
- `GEO_BOOTSTRAP_OIDC_SUBJECT` 必须等于 IdP token 的 `sub`；
- `GEO_BOOTSTRAP_TENANT_ID` 必须等于 token 中由 `GEO_OIDC_TENANT_CLAIM` 指定的 claim；
- email/display name 只用于身份资料，不参与认证；tenant/project UUID 由运维预先生成并留档。

执行显式 one-shot profile；普通 `production-up` 不会运行此服务：

```bash
make production-provision-owner PROD_ENV=infra/production.env
```

该命令只使用 installer Secret，在一个短事务内创建首 tenant、OIDC identity、首 project
和 owner membership，并追加 `tenant.bootstrap` 审计。成功输出仅包含四个公开字段：
tenant/identity/project ID 与 `replayed`。相同配置可安全重放；任何部分存在或字段不同都会
fail closed，绝不覆盖。完成后使用该 OIDC owner 登录，即可通过稳定 `POST /v1/projects`
创建后续项目。不要把 provisioning profile 加入常驻启动命令。

## 5. 管理内部 OIDC 成员

Internal API 不创建 IdP 账号；先在 IdP 创建用户并取得其精确 `iss`、`sub`、email 和
display name，再由项目 owner/admin 调用成员 API。每个 mutation 都必须使用新的
`Idempotency-Key`；同 key、同请求会返回冻结结果，复用同 key 执行不同请求会返回 409。

```bash
curl -X POST "$INTERNAL_API/v1/projects/$PROJECT_ID/members" \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H "Idempotency-Key: member-add-$(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"issuer":"https://idp.example/","subject":"user-sub","email":"user@example.com","display_name":"Content Reviewer","role":"analyst"}'
```

可用命令为：

- `GET /v1/projects/{project_id}/members`：列出 active/revoked 历史成员；
- `POST /v1/projects/{project_id}/members`：绑定 `owner/admin/analyst` OIDC 身份；
- `POST /v1/projects/{project_id}/members/{membership_id}/role`：显式变更角色；
- `POST /v1/projects/{project_id}/members/{membership_id}/revoke`：撤销访问；
- `POST /v1/projects/{project_id}/members/{membership_id}/reactivate`：恢复误撤销成员。

只有 owner 可以新增、撤销、恢复或改写 owner；admin 只能管理 admin/analyst。系统拒绝
删除或降级最后一个 active owner，也拒绝导致项目没有 manager 的自撤销/自降级。OIDC
identity 已存在但资料不同、或对 revoked 成员再次调用 add，都会 fail closed；必须核对
IdP 后使用显式 role/reactivate 命令。所有实际变化分别记录 `member.added`、
`member.role_changed`、`member.revoked`、`member.reactivated` 追加式审计。

## 6. 验收

- Customer API 请求 `/v1/engineering/*`、`/v1/dev-tools/*` 和内部管理路径均为 404。
- Admin `/api/auth/login` 只跳转到 allowlist 中的 OIDC HTTPS origin；缺配置或非法 URL 必须返回 503。
- Dev Tools 环境变量固定为 0。
- 日志只有 JSON 元数据，不包含 Authorization、Cookie、Prompt、正文或模型响应。
- `/health` 在依赖故障时仍能表达进程存活；`/ready` 和 Compose health 与依赖及 heartbeat 一致。
- Worker 可接管租约过期任务，且重复消息不会产生第二份业务结果。
- 使用新建项目完成一次受控 DeepSeek 文案生成和人工审核。
- 按 [认证加密备份与恢复](backup-restore.md) 生成一次已提交备份并完成隔离恢复；receipt 必须包含 PostgreSQL 业务计数/FK、四张核心关系的源/恢复确定性 hash，以及 `geo-artifacts`、`geo-restricted-recommendation-artifacts`、`geo-restricted-workflow-c-artifacts`、`geo-synthetic-style-raw`、`geo-synthetic-style-derived` 五个 bucket 各自的逐对象 hash。Secret Store、Provider Artifact、Synthetic Artifact、Recommendation Artifact、Workflow C Artifact 五个应用加密域必须各自完成全部在用 key-version canary 和代表 secret/artifact 认证解密。任一必需 Artifact 域为零行或只验证 ciphertext/hash 都不得通过。禁止用 mock、明文 dump、磁盘明文 staging 或仅校验 catalog 代替。

## 7. 升级与回退

本项目当前只支持维护窗口内的单版本原子升级，不支持旧 API、Web、Worker 或 Relay
与新数据库混跑，也不支持跨本次合同变更的滚动升级。稳定 OpenAPI 快照用于检测合同变化，
不等同于自动提供旧客户端后向兼容层。任何仓库外 `/v1` 调用方都必须在维护窗口前完成
请求参数、请求体和响应类型迁移。

升级按以下顺序执行：

1. 在隔离环境恢复最新生产备份，使用候选镜像完整演练 `alembic upgrade head`、登录、
   历史数据读取和核心任务处理。升级脚本包含严格的数据完整性门禁；演练失败时不得在
   生产库继续尝试或手工跳过。
2. 固定一个发布清单，记录 Internal/Customer API、Admin/Customer Web、Task/Style Browser
   Worker、Relay、Style registry hash 和 migrate 镜像的精确 digest。不得在同一窗口混用
   不同发布清单。
3. 启用反向代理维护页，停止 API 和两个 Web 的新输入；暂停 Relay，停止 Worker 领取新任务。
   等待当前任务完成，或记录经本版本明确支持续跑的历史任务。确认 Outbox 及
   `queued/retry_wait/running/finalizing` 任务不存在未解释积压。
4. 停止 API、Web、Worker 和 Relay，创建并校验 PostgreSQL 与对象存储的升级前备份。
   备份标识、发布清单和维护窗口写入变更记录。
5. 在旧进程全部停止后，仅使用候选发布的 `migrate` 镜像执行 `alembic upgrade head`。
   迁移成功后以同一发布清单启动两个 API、两个 Web、Worker 和 Relay。
6. 保持维护页，验证 `/health`、`/ready`、Worker/Relay heartbeat、队列卡滞检查、OIDC
   登录、历史记录读取，以及一次不产生外部发布的核心 smoke。全部通过后才恢复流量。

回退只能在恢复流量前进行：停止全部候选进程，将 PostgreSQL 和对象存储恢复到升级前
一致性备份，再启动完整旧版发布清单。新版本产生写入后不得通过 Alembic downgrade 或只
回退应用镜像恢复服务；必须整体恢复升级前快照。若已恢复外部流量，则先重新进入维护窗口，
按事故流程评估新写入，再决定前向修复或全量恢复。
