"use client";

import styles from "../features/workflow-c/WorkflowCStates.module.css";

export default function WorkflowCError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className={styles.errorPage} role="alert">
      <p className={styles.kicker}>GEO measurement control</p>
      <h1>工作区暂时无法加载</h1>
      <p>请求没有改变任何采样、指标或告警记录。可以重试，或返回项目列表检查环境状态。</p>
      {error.digest ? <code>错误摘要：{error.digest}</code> : null}
      <nav aria-label="错误恢复操作">
        <button onClick={reset} type="button">重试</button>
        <a href="/projects">返回项目列表</a>
      </nav>
    </main>
  );
}
