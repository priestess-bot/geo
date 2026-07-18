# GEO Prompt 目录

这里是仓库内所有模型提示词和默认输出合同的唯一文件真源。Python 和前端不得再复制
这些提示词正文。

## 目录职责

```text
prompt/
  catalog.json                 九渠道 task/skill/file 映射
  common/
    system.md                  默认 Prompt Release System Prompt
    user-template.md           Brief/Evidence/Policy 用户模板
    evidence-led-*.md          共享证据驱动生成协议
    test-only-*.md             测试消费者语气规则
  channels/                    每个平台一个可独立编辑的渠道 Prompt
  runtime/
    generation-system.md       正式 Generation Worker 输出边界
    simulation-system.md       TEST ONLY Simulation Worker 输出边界
    authenticity/              brand/fake persona/synthetic testimonial 规则
  contracts/
    placement-output-schema.json
```

`[[name]]` 是文件组装阶段使用的内部变量，必须由加载器完全解析。`{{ brief }}`、
`{{ evidence }}` 和 `{{ destination_policy }}` 是 Prompt Release 的服务端权威变量，
只能在冻结 Prompt Bundle 时填充。不要互换两种语法。

## 修改并发布

1. 只修改对应 `.md` 文件；新增渠道时同步修改 `catalog.json`。
2. 执行 `uv run pytest tests/unit/placements/test_default_prompts.py -q`。
3. Docker 开发环境会把本目录只读挂载到 `/app/prompt`；目录同步和模型请求会重新读取
   文件，不需要重建镜像。生产环境需用修改后的目录重新构建和部署镜像。也可使用
   `GEO_PROMPT_ROOT` 指向另一套完整目录。
4. 在 Admin Web 点击“同步九平台文件 Prompt”。系统会为变化后的文件创建新的不可变
   Prompt Release，但不会覆盖项目已经选择的 Release。
5. 检查新 Release 的源码和 hash，显式切换相应 `task_key` 的绑定，然后创建新的 Prompt
   Bundle。历史 Release、Bundle、Generation 和审核记录保持不变。

修改 `runtime/` 会改变后续模型请求的运行时边界，不创建数据库 Prompt Release；请求
hash 和模型调用日志仍会记录实际发送内容。此类修改必须与 Worker 代码一起经过回归并
随部署发布。

## 加载保护

加载器拒绝目录穿越、绝对路径、缺失文件、空文件、无效 JSON、重复 task/skill 和未解析
的内部变量。生产镜像通过 `apps/api/Dockerfile` 复制本目录，缺失时服务会快速失败，而不
会回退到代码里的旧提示词。
