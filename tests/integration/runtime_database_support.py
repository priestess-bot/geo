from __future__ import annotations

import os

from psycopg.conninfo import conninfo_to_dict, make_conninfo


_ROLE_PASSWORDS = {
    "geo_app_dev": ("GEO_DEV_APP_PASSWORD", "geo_app_dev"),
    "geo_worker_dev": ("GEO_DEV_WORKER_PASSWORD", "geo_worker_dev"),
}


def runtime_role_url(database_url: str, *, user: str) -> str:
    try:
        environment_name, development_default = _ROLE_PASSWORDS[user]
    except KeyError as exc:
        raise ValueError(f"unsupported GEO runtime role: {user}") from exc
    password = os.getenv(environment_name, "").strip() or development_default
    parameters = conninfo_to_dict(database_url)
    return make_conninfo(**{**parameters, "user": user, "password": password})
