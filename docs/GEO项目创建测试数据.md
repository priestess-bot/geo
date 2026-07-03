# GEO 项目创建测试数据

本文档提供一套可用于 Admin Web `/projects/new` 页面手工测试的 GEO 项目创建数据。

访问地址示例：

```text
http://localhost:18005/projects/new
```

实际端口以 `make docker-up-auto-ports` 输出为准。

## 1. 租户与项目

租户名称：

```text
BrightLab Test Tenant
```

项目名称：

```text
BrightLab GEO Pilot
```

## 2. 品牌与官网

目标品牌：

```text
KoalaHome
```

品类：

```text
DTC home furniture and bedding
```

官网域名：

```text
koalahome.example
```

母公司：

```text
KoalaHome Group
```

## 3. 竞品范围

竞品名称：

```text
SleepyJoey
AussieNest
CloudMattress
```

竞品域名：

```text
sleepyjoey.example
aussienest.example
cloudmattress.example
```

说明：当前创建流程要求竞品名称为 3 到 5 个。这套数据正好提供 3 个竞品，可通过校验。

## 4. 客户入口

客户邮箱：

```text
customer+koalahome@example.com
```

项目 owner：

```text
runtime-console
```

## 5. 采集与外部调用

采集模式：

```text
fixture
```

启动状态：

```text
draft
```

调度配置 JSON：

```json
{"cadence":"weekly","timezone":"Australia/Sydney","weekday":"monday"}
```

连接器配置 JSON：

```json
{"openai":{"status":"not_configured"},"perplexity":{"status":"not_configured"},"google_ai_mode":{"status":"fixture_only"}}
```

## 6. 预期结果

点击“创建项目”后，页面应返回：

- 项目已创建提示
- 项目详情入口
- 客户邀请入口
- 一次性 raw invite token

后续可进入项目详情页，继续测试：

- 创建客户邀请
- 生成 portal token
- 撤销 portal token
- 查看 runtime 数据摘要

也可以使用客户邀请入口或 portal token 打开 Customer Web，验证客户侧单项目门户。
