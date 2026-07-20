Return JSON matching the frozen output schema. Use only the brief, destination policy and
evidence in this prompt bundle. Return JSON only. Keep internal_evidence_refs separate
from public_citation_refs; public refs must obey the frozen disclosure, attribution and
quotation metadata. In content_json, always return required_disclosures and expected_links
as explicit string arrays. Copy required disclosure wording from the frozen Destination policy;
use empty arrays only when the policy does not require disclosure or links. Frozen output schema:
[[output_schema]]
