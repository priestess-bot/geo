# 从头新建 GEO 项目操作指南

本文档说明如何在当前工程中从零创建一个 GEO 项目，并让内部 Admin Web 与客户 Customer Web 都能访问同一个项目数据。

## 1. 启动服务

在项目根目录执行：

```bash
cd /home/ymm/ym/gz/20260608-geo
make docker-up-auto-ports
```

该命令会自动寻找可用端口，并启动：

- PostgreSQL
- MinIO
- API
- Customer Web
- Admin Web
- Dashboard Web

启动成功后，终端会打印本次实际访问地址。以上次启动为例：

- Admin Web: `http://localhost:18012`
- Customer Web: `http://localhost:18011`
- Dashboard Web: `http://localhost:18013`
- API: `http://localhost:18010`
- API docs: `http://localhost:18010/docs`

每次自动端口可能不同，请以终端输出为准。

## 2. 打开 Admin Web

在浏览器打开 Admin Web，然后进入项目创建向导：

```text
/projects/new
```

Admin Web 是内部使用页面，用于创建项目、管理客户入口、查看项目 runtime 数据和处理 token。

## 3. 填写租户与项目

在“租户与项目”区域填写：

- 租户名称：客户公司或内部客户分组，例如 `Design Partner AU`
- 项目名称：内部项目名，例如 `AU GEO Pilot`

这两个字段用于内部管理和项目归属。

## 4. 填写品牌与官网

在“品牌与官网”区域填写：

- 目标品牌：客户品牌名
- 品类：项目所属品类，例如 `DTC ecommerce products`
- 官网域名：客户主域名，例如 `example.com`
- 母公司：可选

官网域名会写入项目启动配置，并显示在客户门户中。

## 5. 填写竞品范围

在“竞品范围”区域填写 3 到 5 个竞品。

竞品名称示例：

```text
Competitor A
Competitor B
Competitor C
```

竞品域名可选，但建议填写：

```text
competitor-a.com
competitor-b.com
competitor-c.com
```

当前首期创建流程要求竞品名称数量为 3 到 5 个，避免评分和对比维度过少或过宽。

## 6. 配置客户入口

在“客户入口”区域填写：

- 客户邮箱：用于生成 viewer 邀请
- 项目 owner：可以先使用默认值 `runtime-console`

项目创建成功后，系统会生成客户邀请。客户首次使用邀请链接进入 Customer Web 后，可以换取 portal token。

## 7. 配置采集与外部调用

第一次创建项目建议使用保守配置：

- 采集模式：`fixture`
- 启动状态：`draft`
- 调度配置 JSON：

```json
{"cadence":"weekly"}
```

- 连接器配置 JSON：

```json
{}
```

当真实 OpenAI、Perplexity、Google 或浏览器采集环境准备好后，再切换到真实采集和真实外部调用路径。

## 8. 创建项目

点击“创建项目”。

创建成功后，页面会显示：

- 项目详情入口
- 客户邀请入口
- 一次性 raw invite token

注意：raw invite token 只显示一次，应立即记录或直接使用生成的客户邀请链接。

## 9. 进入项目详情

点击“打开项目详情”后，可以查看：

- 项目配置
- 启动配置
- 成员
- 邀请
- portal token 元数据
- 评分快照
- 报告
- 报告任务
- 行动计划
- 信源图谱

项目详情页还可以执行：

- 创建新的客户邀请
- 生成 portal token
- 撤销 portal token

portal token 的 raw token 也只显示一次。

## 10. 客户进入 Customer Web

客户有两种进入方式：

1. 使用 Admin Web 生成的客户邀请链接。
2. 在 Customer Web 首页输入 portal token。

Customer Web 只展示绑定到当前 token 的单个项目，不展示内部项目列表和内部排障信息。

客户可见模块包括：

- AI 可见度
- 信源与竞品
- 证据样本
- 报告交付
- 下一步行动
- 交付包
- 可解释性

## 11. 查看报告交付物

在 Customer Web 的“报告交付”或“交付包”模块中，可以下载：

- Markdown
- CSV
- PDF

下载由 Customer Web 代理完成：页面先校验 portal token，再用客户成员身份访问后端报告 artifact。

## 12. 停止服务

完成操作后，在项目根目录执行：

```bash
make docker-down-auto-ports
```

该命令会停止通过自动端口方式启动的服务。

## 13. 最短操作路径

如果只需要快速跑通一次完整流程，按下面顺序执行：

1. `make docker-up-auto-ports`
2. 打开 Admin Web。
3. 进入 `/projects/new`。
4. 填写品牌、官网、3 到 5 个竞品、客户邮箱。
5. 采集模式选择 `fixture`，启动状态选择 `draft`。
6. 点击“创建项目”。
7. 打开项目详情。
8. 使用客户邀请链接或 portal token 打开 Customer Web。
9. 在 Customer Web 查看项目模块和报告交付物。
10. 完成后执行 `make docker-down-auto-ports`。
