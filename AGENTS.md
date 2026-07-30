# GEO Repository Instructions

## 运行流程可视化同步

修改代码后，如果新增、删除或改变以下任一内容，必须在同一任务中同步更新 `docs/architecture/GEO-runtime-flow-visualization.html`：

- 业务输入、知识、内容、合成测评、观测统计、建议、发布、客户交付或归因流程；
- Durable Job、Outbox、Worker、Dify、Provider、Browser Capture 或 Connector 的任务链路；
- Web、API、PostgreSQL、MinIO、Valkey、Dify 或专用 Worker 的部署运行关系；
- 会改变流程节点真实状态、数量、阻塞原因、下一步动作或验收依据的数据合同。

可视化必须反映当前真实实现和已验证状态，不能把 fixture、mock、技术 Canary 或进程健康冒充为真实业务结果。必须明确区分已完成、技术通过但业务不足、等待人工、外部阻塞和尚未开始。

完成前使用 Chromium 实际渲染至少一个桌面视口和一个移动视口，检查三个视图、主要交互、文字清晰度、遮挡、横向溢出和控制台错误。只检查 HTML 源码不算完成。
