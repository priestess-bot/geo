from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0090_prompt_workspace.py"
UP = ROOT / "infra/db/alembic/sql/0090_prompt_workspace.sql"
DOWN = ROOT / "infra/db/alembic/sql/0090_prompt_workspace.down.sql"
REPOSITORY = ROOT / "packages/geo_core/geo_core/prompts/postgres_repository.py"


def test_prompt_workspace_is_the_linear_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0090_prompt_workspace"' in source
    assert 'down_revision = "0089_recommendation_keyring"' in source
    assert UP.is_file() and DOWN.is_file()


def test_prompt_workspace_is_scoped_editable_and_single_operator_publishable() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "CREATE TABLE prompt_program_working_drafts",
        "PRIMARY KEY (project_id, program_id)",
        "candidate_release_id uuid",
        "revision bigint NOT NULL",
        "geo_jsonb_canonical_text(jsonb_build_object",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "CREATE POLICY project_scope",
        "GRANT SELECT, INSERT, UPDATE ON prompt_program_working_drafts TO geo_app",
        "CREATE OR REPLACE FUNCTION geo_assert_prompt_program_state_append()",
    ):
        assert contract in source
    assert "owner cannot approve" not in source
    assert "GRANT DELETE" not in source


def test_new_program_creation_initializes_the_draft_in_the_same_transaction() -> None:
    source = REPOSITORY.read_text(encoding="utf-8")
    create_section = source.split("def store_created_program", maxsplit=1)[1].split(
        "def store_release_transition", maxsplit=1
    )[0]
    assert "INSERT INTO prompt_program_working_drafts" in create_section
    assert create_section.index("INSERT INTO prompt_program_working_drafts") < (
        create_section.index("self._insert_command(command)")
    )


def test_prompt_workspace_downgrade_refuses_to_discard_edits() -> None:
    source = DOWN.read_text(encoding="utf-8")
    for guard in (
        "draft.revision > 1",
        "draft.candidate_release_id IS NOT NULL",
        "draft.system_template <> release.system_template",
        "cannot downgrade: editable Prompt workspace data exists",
    ):
        assert guard in source
    assert "Prompt Program owner cannot approve own Release" in source
