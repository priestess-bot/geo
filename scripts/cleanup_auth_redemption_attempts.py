#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

import psycopg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Erase expired Auth delivery ciphertext in bounded batches.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--all", action="store_true", help="Continue until no expired ciphertext remains.")
    return parser.parse_args()


def erase_batch(connection: psycopg.Connection[object], *, batch_size: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH expired AS (
              SELECT id
              FROM auth_invitation_redemption_attempts
              WHERE delivery_ciphertext IS NOT NULL
                AND delivery_expires_at <= now()
              ORDER BY delivery_expires_at, id
              FOR UPDATE SKIP LOCKED
              LIMIT %s
            )
            UPDATE auth_invitation_redemption_attempts attempt
            SET delivery_ciphertext = NULL,
                delivery_key_id = NULL,
                delivery_nonce = NULL,
                secret_erased_at = coalesce(attempt.secret_erased_at, now()),
                updated_at = now()
            FROM expired
            WHERE attempt.id = expired.id
            """,
            (batch_size,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def delete_expired_preflight_buckets(connection: psycopg.Connection[object], *, batch_size: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH expired AS (
              SELECT bucket_key
              FROM auth_preflight_rate_limits
              WHERE expires_at <= now()
              ORDER BY expires_at, bucket_key
              FOR UPDATE SKIP LOCKED
              LIMIT %s
            )
            DELETE FROM auth_preflight_rate_limits rate_limit
            USING expired
            WHERE rate_limit.bucket_key = expired.bucket_key
            """,
            (batch_size,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 10_000:
        raise SystemExit("--batch-size must be between 1 and 10000")
    database_url = os.getenv("AUTH_MAINTENANCE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("AUTH_MAINTENANCE_DATABASE_URL or DATABASE_URL is required")
    total = 0
    rate_limit_total = 0
    batches = 0
    with psycopg.connect(database_url) as connection:
        while True:
            erased = erase_batch(connection, batch_size=args.batch_size)
            deleted_buckets = delete_expired_preflight_buckets(connection, batch_size=args.batch_size)
            total += erased
            rate_limit_total += deleted_buckets
            batches += 1
            if not args.all or (erased < args.batch_size and deleted_buckets < args.batch_size):
                break
    print(
        json.dumps(
            {
                "batches": batches,
                "ciphertexts_erased": total,
                "preflight_buckets_deleted": rate_limit_total,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
