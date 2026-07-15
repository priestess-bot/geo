# ADR-0003：Prompt 与流程解耦

状态：Accepted

Skill Version 是可编辑规则源，Template Release 是不可变编译产物，Prompt Bundle 冻结一次生成所需的模板、变量、Evidence Pack、模型政策和预算。修改提示词不需要修改工作流代码；已执行任务仍能重放当时的确切输入。
