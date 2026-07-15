# 备份与恢复

系统采用轻量备份目标，不承诺 PITR 或正式 RPO/RTO：每日生成 PostgreSQL dump，并把 MinIO 工件镜像到独立 `GEO_BACKUP_ROOT`；保留 7 个日备和 4 个周备。

## 每日备份

由 cron 或 systemd timer 执行：

```bash
scripts/backup_geo_data.sh infra/production.env
```

输出目录包含 `postgres.sql.gz`、`SHA256SUMS` 和 MinIO 镜像。备份根目录必须位于不同磁盘或远端挂载，不能与 PostgreSQL/MinIO 数据卷共存。

## 恢复冒烟

选择最新日备，在隔离的 tmpfs PostgreSQL 服务中恢复：

```bash
scripts/restore_geo_backup_smoke.sh \
  infra/production.env \
  /srv/geo-backups/daily/<timestamp>/postgres.sql.gz
```

该命令不会写入生产数据库。它启动 `restore-smoke-postgres`、恢复 SQL、检查 catalog 后销毁临时实例。至少每月运行一次，并将成功时间记录到 Development Board 的 Release Evidence。
