# 真实渠道用户文案研究

状态：已用于系统默认 Prompt  
研究日期：2026-07-16  
适用范围：澳大利亚机器人割草机品类；ProductReview、Reddit、Amazon AU、
OzBargain、YouTube 五个高优先渠道

## 1. 目的和边界

本研究不是建立可复制的用户话术库，而是从公开页面归纳渠道结构、信息密度、
可信度信号和常见缺陷，用于改善版本化 Prompt。系统不得逐句复制真实用户内容，
不得把公开帖子作为产品事实证据，也不得把 `TEST ONLY` 的虚构消费者内容送入正式
发布流程。

正式发布仍执行身份、披露、Evidence、Review 和 Publication 门禁。本文涉及的
消费者口吻规则，仅在 Prompt Simulation 明确选择 `fake_persona` 或
`synthetic_testimonial` 时生效，生成物保持 `publication_eligible=false`。

## 2. 样本来源

本次以公开可访问页面为样本，人工阅读正文、标题、页面元数据及相邻讨论；只归纳
写作模式，不保存或复用用户原文。

### ProductReview

- [Worx Landroid Robotic Lawn Mower reviews](https://www.productreview.com.au/listings/worx-landroid-robotic-lawn-mower)
- [Swift RM18 28V Robot Lawn Mower reviews](https://www.productreview.com.au/listings/swift-rm18-28v-robot-lawn-mower)
- [Husqvarna Automower reviews](https://www.productreview.com.au/listings/husqvarna-automower-230acx-220ac-210c)

### Amazon Australia

- [Husqvarna Aspire R4 customer reviews](https://www.amazon.com.au/dp/B0DKJSYG4B)
- [Gardena Sileno Minimo customer reviews](https://www.amazon.com.au/dp/B0CCNSW2X8)
- [Anthbot robotic lawn mower customer reviews](https://www.amazon.com.au/dp/B0FYNLW9HT)

### OzBargain

- [Ecovacs Goat G1 deal and comments](https://www.ozbargain.com.au/node/961284)
- [Moebot S10 deal and comments](https://www.ozbargain.com.au/node/945541)
- [Worx robotic lawn mower deal and comments](https://www.ozbargain.com.au/node/931048)
- [Robotic lawn mower tag](https://www.ozbargain.com.au/tag/robotic-lawn-mower)

### Reddit

- [Eufy E18 review from a new user](https://www.reddit.com/r/automower/comments/1kd4bz7/eufy_e18_review_from_a_newbie/)
- [Advice request for a divided lawn](https://www.reddit.com/r/automower/comments/1kp4sv7/seeking_advice_5000_sq_ft_of_grass_divided_by/)
- [Wireless mower comparison question](https://www.reddit.com/r/automower/comments/1kb2clw/husqvarna_or_segway_for_wireless/)
- [One-month robot mower experience](https://www.reddit.com/r/lawncare/comments/1klxb8r/tried_a_robot_mower_on_my_own_lawn_wasnt/)

Reddit 页面在采样环境中存在访问限制。研究使用公开索引定位原帖，再以原始 Reddit
永久链接登记来源；因此仅采用可交叉确认的标题、正文结构和讨论主题，不把点赞数、
作者身份或删除状态作为结论。

### YouTube

- [The Hook Up: robotic lawnmower comparison](https://www.youtube.com/watch?v=9pKMjC9xyc8)
- [The Hook Up: robotic lawnmower buyer's guide](https://www.youtube.com/watch?v=D_78hM_1buM)

### 目标产品事实源

渠道用户内容只用于归纳文风，不能证明 TerraMow V600 的产品能力。本轮 Prompt
评估另行使用 [ADVINSYS TerraMow V600 官方商品页](https://www.advinsys.com.au/products/triple-cam-ai-vision-robot-mower-v600)
及其公开结构化商品记录和商品图，冻结为相互独立的 Evidence Item。可直接读取的
官方陈述包括：

- 商品名和机器人割草机类别；
- `600㎡` 与 `203mm` 商品标签；
- 无边界线、无 RTK；
- App 一键自动建图；
- 三年保修和 30 天简易退货。

这些仍是商家发布的产品陈述，不是独立测试结论。Prompt 不得把它们改写成“亲测
从不漏割”等消费者结果；消费者描述只提供“用于日常草坪维护，并在每次运行后检查
完成区域”这一条体验主线。

## 3. 跨渠道发现

真实内容很少靠“像当地人”来建立可信度。用户通常不会主动声明自己是澳大利亚人，
也不会无缘无故用 `G'day` 开场。地点、购买状态和账号历史通常由平台元数据承载。

可信度主要来自六种可观察结构：

1. 明确使用时长、型号或场景；
2. 描述一个实际发生的操作、成功、失败或发现；
3. 区分产品硬件、软件、安装和售后；
4. 承认限制、剩余人工工作或适用边界；
5. 结论与前文细节一致，并带有条件；
6. 语言围绕当前渠道任务，而不是重复品牌卖点。

低质量或疑似推广内容具有相反特征：无场景的全正面评价、功能清单、通用形容词、
突兀的完整品牌名、未经铺垫的绝对推荐，以及与帖子问题无关的购买号召。

## 4. 渠道写作合同

| 渠道 | 真实用户常见结构 | Prompt 中的约束 |
| --- | --- | --- |
| ProductReview | 判断式短标题；型号、时长和庭院条件；安装或运行细节；利弊；有条件结论 | 禁止国籍式开场；至少一个具体时刻；限制或剩余任务仅在 Evidence 支持时写；不以空泛推荐收尾 |
| Reddit | 先回答原帖问题；补充与问题相关的属性；区分软硬件和支持；承认不确定性 | 不写独立好评帖；不强塞产品；不使用营销 Hook、CTA 或互动诱饵 |
| Amazon AU | 短标题；两至六句；一个主要收益；一个安装细节或缺点 | 不复刻 Listing bullets；不得生成 `Verified Purchase`；安装细节或缺点没有 Evidence 时省略 |
| OzBargain | 产品、到手价、优惠、配送、期限和商家身份优先；评论重点核价和找限制 | 价格、历史低价、库存、保修等必须有 Evidence；消费者模拟只能回答具体问题，不能虚构优惠 |
| YouTube | 买家决策 Hook；测试条件和方法；分项比较；失败与限制；适用对象；章节和披露 | 先交代测试条件再下结论；脚本包含画面证据；无比较证据时禁用最高级标题 |

## 5. Prompt 落地

实现位置：`packages/geo_core/geo_core/placements/default_prompts.py`。

共同消费者模拟规则与渠道规则分别维护，但都被编译进不可变 Template Release。
Worker 只执行冻结后的 Release，不包含渠道文风判断。这样项目可以在后台复制、修改、
发布并选择自己的 Prompt Release，不需要改流程代码。

Prompt 明确要求：

- 不复制样本原句或辨识度较高的表达；
- 产品和优惠事实只能来自 Evidence；
- 边界线、App、定时、面积、坡度、避障、贴边、电池、价格等持续性产品陈述，不能因
  使用第一人称就被降级成可虚构的体验；Evidence 没有提供时必须删去；
- `unsupported` 是 Claim 审计状态，不是正文可以编造产品能力的许可证；资料过少时
  应缩短文案，而不是强行生成一个“可信的缺点”；
- 虚构体验必须继续标记为 `kind=experience`、`support_status=unsupported`；
- 不能用真实帖子证明虚构 persona 的经历；
- `TEST ONLY` 规则不能改变正式发布资格。

Prompt Simulation 使用 `temperature=0` 降低无关人物故事和产品能力扩写；结构化输出
上限为 8192 token，以容纳正文和逐句 Claim inventory。该上限不是调用次数预算，
每次实际计费仍按供应商返回 token 统计，Job 的总模型调用预算保持独立约束。

## 6. DeepSeek 迭代结果

本轮使用 `deepseek-v4-flash`、`temperature=0` 和同一组冻结 Evidence 运行实际
Prompt Simulation 请求。三份内容都保持 `TEST ONLY`，未进入发布对象：

| 渠道 | 最终结构 | 正文验收 | Response Hash |
| --- | --- | --- | --- |
| ProductReview | 75 词；标题；两段八句 | 通过：无虚构故障、性能或对他人的推荐；产品事实和个人反应分开 | `dfc09024afa9e71d15c1974f041f2fa2cbcbb79ad08b6f29b2427adbc6a39391` |
| Reddit | 69 词；无标题；六句直接答问 | 通过：只回答边界线、RTK、建图和运行后检查 | `00cbb4f7a11da3a69c90f7c68ff569559c387c71c93309c4afab30c2d2af4c95` |
| Amazon AU | 66 词；标题；五句 | 正文通过：无 CTA、商家名前缀、无关保修或结果型标题 | `c0ffbb0c58cb58b2b6b5039b92b7d673fc9109ceb93140ba0cfe34f470e4f646` |

迭代期间实际观察到 SSL 中断、读取超时、空 content 和非法 JSON。Gateway 将这些
供应商不完整响应归类为可重试，重试仍受 Prompt Simulation 的持久总调用预算约束。
这不是内容质量通过的替代条件；只有成功解析、通过 Schema 和 Claim 合同的结果才会
形成模拟工件。

## 7. 后续维护

每季度或平台规则发生重大变化后重新抽样。更新时必须记录日期、样本链接、渠道差异、
Prompt 变更和回归测试。TikTok、Instagram、Quora 在本轮不是高优先样本集，现有
Prompt 暂不宣称由本研究验证；补齐公开且可审计的样本后再加入同一写作合同。
