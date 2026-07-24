from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import os
import random
import subprocess
import sys

from geo_core.statistical_methods import (
    PairedObservation,
    StatisticalStratum,
    paired_bootstrap,
)


def test_paired_bootstrap_is_stable_across_order_retries_and_global_rng() -> None:
    pairs = _pairs()
    first = paired_bootstrap(
        pairs,
        seed_hex="f" * 64,
        iterations=1_000,
        alpha=Decimal("0.05"),
    )
    random.seed(123456)
    second = paired_bootstrap(
        tuple(reversed(pairs)),
        seed_hex="f" * 64,
        iterations=1_000,
        alpha=Decimal("0.05"),
    )

    assert first == second
    assert first.point_estimate == Decimal("0.050000000000")
    assert first.distribution_hash == second.distribution_hash


def test_paired_bootstrap_is_stable_across_process_hash_seeds() -> None:
    script = r"""from decimal import Decimal
import json
from geo_core.statistical_methods import PairedObservation, StatisticalStratum, paired_bootstrap
s = StatisticalStratum("openai", "model-v1", "provider_api", "en-AU", "AU", "c"*64, "d"*64, "purchase")
pairs = tuple(PairedObservation(f"p{i}", f"q{i}", "purchase", s.stratum_hash, s.sampling_source_stratum_hash, "provider_api", Decimal("0"), value) for i, value in enumerate((Decimal("0.2"), Decimal("-0.1"), Decimal("0.1"), Decimal("0")), 1))
r = paired_bootstrap(pairs, seed_hex="f"*64, iterations=1000, alpha=Decimal("0.05"))
print(json.dumps({"point": str(r.point_estimate), "low": str(r.interval.low), "high": str(r.interval.high), "p": str(r.two_sided_p_value), "hash": r.distribution_hash}, sort_keys=True))"""
    outputs = []
    for hash_seed in ("1", "987654"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = hash_seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(result.stdout.strip())

    assert outputs[0] == outputs[1]


def test_pair_identity_changes_distribution_lineage_even_with_same_values() -> None:
    pairs = _pairs()
    first = paired_bootstrap(
        pairs,
        seed_hex="f" * 64,
        iterations=500,
        alpha=Decimal("0.05"),
    )
    renamed = tuple(replace(item, pair_id=f"renamed-{index}") for index, item in enumerate(pairs))
    second = paired_bootstrap(
        renamed,
        seed_hex="f" * 64,
        iterations=500,
        alpha=Decimal("0.05"),
    )

    # Pair identity is frozen in ComparisonInput hash; bootstrap values remain statistical peers.
    assert first.point_estimate == second.point_estimate
    assert first.interval == second.interval


def _pairs() -> tuple[PairedObservation, ...]:
    stratum = StatisticalStratum(
        "openai",
        "model-v1",
        "provider_api",
        "en-AU",
        "AU",
        "c" * 64,
        "d" * 64,
        "purchase",
    )
    values = (Decimal("0.20"), Decimal("-0.10"), Decimal("0.10"), Decimal("0"))
    return tuple(
        PairedObservation(
            f"pair-{index}",
            f"question-{index}",
            "purchase",
            stratum.stratum_hash,
            stratum.sampling_source_stratum_hash,
            "provider_api",
            Decimal(0),
            value,
        )
        for index, value in enumerate(values, start=1)
    )
