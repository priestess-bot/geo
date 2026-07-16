from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from geo_core.prompts.domain import (
    PromptCompilationError,
    SkillVersion,
    compile_template,
    render_bundle,
    render_template,
)


def test_skill_compiles_to_immutable_release_and_reproducible_bundle() -> None:
    skill = SkillVersion.create(
        id=uuid4(),
        skill_id=uuid4(),
        version=3,
        source="Write for {{channel}} about {{product}} using only {{evidence}}.",
    )
    release = compile_template(release_id=uuid4(), skill=skill)
    values = {"channel": "YouTube", "product": "Robot Vacuum", "evidence": "Evidence pack 7"}
    arguments = {
        "project_id": uuid4(),
        "brief_version_id": uuid4(),
        "evidence_pack_id": uuid4(),
        "template": release,
        "variables": values,
        "evidence_pack_hash": "e" * 64,
        "model_policy_hash": "m" * 64,
    }

    first = render_bundle(bundle_id=uuid4(), **arguments)
    second = render_bundle(bundle_id=uuid4(), **arguments)

    assert release.required_variables == ("channel", "evidence", "product")
    assert first.rendered_prompt == "Write for YouTube about Robot Vacuum using only Evidence pack 7."
    assert first.bundle_hash == second.bundle_hash
    with pytest.raises(FrozenInstanceError):
        release.template = "changed"  # type: ignore[misc]


def test_prompt_bundle_rejects_missing_variables() -> None:
    skill = SkillVersion.create(
        id=uuid4(),
        skill_id=uuid4(),
        version=1,
        source="Write {{product}} for {{channel}}.",
    )
    release = compile_template(release_id=uuid4(), skill=skill)

    with pytest.raises(PromptCompilationError, match="channel"):
        render_bundle(
            bundle_id=uuid4(),
            project_id=uuid4(),
            brief_version_id=uuid4(),
            evidence_pack_id=uuid4(),
            template=release,
            variables={"product": "Robot Vacuum"},
            evidence_pack_hash="e" * 64,
            model_policy_hash="m" * 64,
        )


def test_release_renders_without_creating_a_formal_bundle() -> None:
    skill = SkillVersion.create(
        id=uuid4(), skill_id=uuid4(), version=1, source="Preview {{brief}}"
    )
    release = compile_template(release_id=uuid4(), skill=skill)

    assert render_template(template=release, variables={"brief": "only"}) == "Preview only"
