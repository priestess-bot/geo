from geo_api.prompt_program_contracts import CreatePromptProgramRequest
from geo_core.prompts import default_prompt_bootstrap_specs
from geo_core.prompts.bootstrap_contracts import thaw_mapping


def test_every_bootstrap_spec_matches_the_existing_admin_create_contract() -> None:
    specs = default_prompt_bootstrap_specs()

    assert len(specs) == 10
    for spec in specs:
        request = CreatePromptProgramRequest.model_validate(
            thaw_mapping(spec.admin_draft_payload())
        )
        assert request.expected_version == 0
        assert request.program_kind == spec.program_kind.value
        assert request.purpose == spec.purpose
        assert request.test_set_id == spec.test_set_id
        assert request.test_set_version == 1
        assert request.model_policy.version == spec.model_policy.version
