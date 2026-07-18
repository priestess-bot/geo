# 生产部署手册

## 1. 准备镜像与 Secret

复制 `infra/production.env.example` 为部署机外部配置 `infra/production.env`，将所有 `@sha256:replace` 替换为实际 digest。创建配置列出的 Secret 文件并设置 mode 0600。应用数据库 URL、安装数据库 URL、MinIO 应用凭据和备份凭据必须使用不同身份。

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
权限超过 `0600` 的 Secret、占位或未固定 digest 的镜像、非 HTTPS OIDC/公开 URL、
无效 Release 版本和运行阈值；错误只输出稳定错误码和配置项名，不输出配置值或
Secret 内容。不要绕过该入口直接启动生产栈。

确认常驻业务服务包含 `internal-api`、`customer-api`、`task-worker`、`outbox-relay`、`admin-web`、`customer-web`、PostgreSQL、MinIO 和 Valkey，并且 `migrate`、`minio-bootstrap` 是受控一次性服务。不得出现 Qdrant、LiteLLM、旧 Dashboard、旧 Web、历史 Worker或虚假的 Prometheus scrape target。Prometheus/Grafana 当前阶段未启用。

生产网络中只有 Internal API 和 Task Worker 同时加入 `backend` 与 `egress`；Customer
API、Relay、PostgreSQL、MinIO 和 Valkey 只能加入内部 `backend`。Customer API 只持有
PostgreSQL 和 Session 所需 Secret，不能获得对象存储、Valkey 或模型凭据。

## 3. 启动

```bash
docker compose --env-file infra/production.env -f infra/compose.prod.yml pull
docker compose --env-file infra/production.env -f infra/compose.prod.yml up -d
docker compose --env-file infra/production.env -f infra/compose.prod.yml ps
```

`migrate` 与 `minio-bootstrap` 必须成功退出，API、Worker 和 Web 才能进入可用状态。确认 `task-worker` 仅挂载 Worker 数据库凭据、对象存储应用凭据和 DeepSeek Key；`outbox-relay` 不需要 DeepSeek Key。Admin/Customer Web 只绑定本机回环地址，外部 TLS、域名和访问控制由受管反向代理提供。

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

## 7. 升级与回退

先执行备份，再拉取新 digest，通过 `migrate` 后滚动 API、Worker、Web。数据库迁移只能向前；应用回退必须兼容已执行迁移，否则从升级前备份恢复到隔离环境重新部署。
