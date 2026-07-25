from contextlib import contextmanager

from scripts import bootstrap_workflow_c_artifact_keyring as bootstrap


class _Connection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_bootstrap_commits_only_the_verified_keyring(
    monkeypatch,
) -> None:
    connection = _Connection()

    @contextmanager
    def connect(_url, *, row_factory):
        assert row_factory is bootstrap.dict_row
        yield connection

    monkeypatch.setattr(bootstrap.psycopg, "connect", connect)
    monkeypatch.setattr(
        bootstrap,
        "load_master_keyring_from_docker_secret",
        lambda path: ("keyring", str(path)),
    )
    monkeypatch.setattr(bootstrap, "EnvelopeCipher", lambda keyring: keyring)
    monkeypatch.setattr(
        bootstrap,
        "synchronize_workflow_c_artifact_master_keys",
        lambda candidate, cipher: (1, 2)
        if candidate is connection and cipher == ("keyring", "/run/keyring.json")
        else (),
    )

    assert bootstrap.bootstrap(
        database_url="postgresql://installer@database/geo",
        keyring_path="/run/keyring.json",
    ) == (1, 2)
    assert (connection.commits, connection.rollbacks) == (1, 0)
