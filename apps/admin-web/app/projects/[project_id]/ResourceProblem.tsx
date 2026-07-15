import type { ProjectLoadProblem } from "../projectTypes";
import styles from "./Catalog.module.css";

export function ResourceProblem({
  label,
  problem
}: {
  label: string;
  problem: ProjectLoadProblem;
}) {
  const title = problem.status === 403
    ? `无权读取${label}`
    : problem.status === 422
      ? `${label}请求无效`
      : `${label}加载失败`;
  return (
    <div className={styles.error} role="alert">
      <strong>{title}</strong><span>{problem.detail}</span>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </div>
  );
}
