import styles from "../features/workflow-c/WorkflowCStates.module.css";

export default function WorkflowCLoading() {
  return (
    <main
      aria-busy="true"
      aria-label="Sampling, evidence and alerts 正在加载"
      className={styles.loadingShell}
    >
      <div className={styles.loadingBar} />
      <div className={styles.loadingBar} />
      <div className={styles.loadingBar} />
    </main>
  );
}
