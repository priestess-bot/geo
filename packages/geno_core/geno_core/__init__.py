"""Core contracts and data models for the GENO AU evidence platform."""

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import build_p0a_collection_plan, run_fixture_collection_slice
from geno_core.geo import StaticAUGeoProvider
from geno_core.industry import build_au_dtc_ecommerce_profile
from geno_core.market import build_au_market_profile
from geno_core.prompt_pack import build_au_dtc_prompt_pack
from geno_core.scoring import AU_VISIBILITY_V1, score_answer_analysis

__all__ = [
    "AU_VISIBILITY_V1",
    "build_au_dtc_ecommerce_profile",
    "build_au_dtc_prompt_pack",
    "build_au_market_profile",
    "build_au_project_bootstrap",
    "build_p0a_collection_plan",
    "run_fixture_collection_slice",
    "score_answer_analysis",
    "StaticAUGeoProvider",
]
