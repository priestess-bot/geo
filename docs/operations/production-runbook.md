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
docker compose --env-file infra/production.env -f infra/compose.prod.yml config -q
```

确认输出中只有 `internal-api`、`customer-api`、`admin-web`、`customer-web`，不存在 Qdrant、LiteLLM、旧 Dashboard 或旧 Web。

## 3. 启动

```bash
docker compose --env-file infra/production.env -f infra/compose.prod.yml pull
docker compose --env-file infra/production.env -f infra/compose.prod.yml up -d
docker compose --env-file infra/production.env -f infra/compose.prod.yml ps
```

`migrate` 必须成功退出，API 和 Web 才能进入 healthy。Admin/Customer Web 只绑定本机回环地址，外部 TLS、域名和访问控制由受管反向代理提供。

## 4. 验收

- Customer API 请求 `/v1/engineering/*`、`/v1/dev-tools/*` 和内部管理路径均为 404。
- Admin `/api/auth/login` 只跳转到 allowlist 中的 OIDC HTTPS origin；缺配置或非法 URL 必须返回 503。
- Dev Tools 环境变量固定为 0。
- 日志只有 JSON 元数据，不包含 Authorization、Cookie、Prompt、正文或模型响应。
- Worker 可接管租约过期任务，且重复消息不会产生第二份业务结果。
- 使用新建项目完成一次受控 DeepSeek 文案生成和人工审核。

## 5. 升级与回退

先执行备份，再拉取新 digest，通过 `migrate` 后滚动 API、Worker、Web。数据库迁移只能向前；应用回退必须兼容已执行迁移，否则从升级前备份恢复到隔离环境重新部署。
