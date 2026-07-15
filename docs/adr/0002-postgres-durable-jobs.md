# ADR-0002：PostgreSQL Durable Job

状态：Accepted

PostgreSQL 是任务状态真源，Dramatiq/Valkey 只负责唤醒。任务支持 lease、heartbeat、fencing token、过期接管、retry、regenerate、operator replay、Outbox 和 dead letter。批量任务拆分为独立子任务，不使用含义不清的 `partial_succeeded`。
