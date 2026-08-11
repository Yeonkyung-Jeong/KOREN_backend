import random

import pytest

from scripts.seed_mock_summaries import (
    ANATOMY_SITE_KOR,
    FOLLOWUP_LONG_POOL,
    FOLLOWUP_SHORT_POOL,
    pick_followup_plan,
    pick_의사소견,
    pick_처방,
    pick_환자우려점,
    의사소견_TEMPLATES,
    처방_POOL,
    환자우려점_POOL,
)


@pytest.mark.parametrize("diagnosis", ["benign", "malignant"])
def test_pick_처방_always_from_matching_pool(diagnosis):
    rng = random.Random(0)
    for _ in range(20):
        assert pick_처방(rng, diagnosis) in 처방_POOL[diagnosis]


@pytest.mark.parametrize("diagnosis", ["benign", "malignant"])
def test_pick_환자우려점_always_from_matching_pool(diagnosis):
    rng = random.Random(0)
    for _ in range(20):
        assert pick_환자우려점(rng, diagnosis) in 환자우려점_POOL[diagnosis]


@pytest.mark.parametrize("diagnosis,anatomy_site", [
    ("benign", "torso"),
    ("malignant", "head_neck"),
])
def test_pick_의사소견_includes_site_label(diagnosis, anatomy_site):
    rng = random.Random(0)
    result = pick_의사소견(rng, diagnosis, anatomy_site)
    assert ANATOMY_SITE_KOR[anatomy_site] in result
    assert result in [t.format(site=ANATOMY_SITE_KOR[anatomy_site]) for t in 의사소견_TEMPLATES[diagnosis]]


def test_pick_followup_plan_shorter_when_previous_malignant():
    rng = random.Random(0)
    for _ in range(20):
        assert pick_followup_plan(rng, "malignant") in FOLLOWUP_SHORT_POOL


@pytest.mark.parametrize("previous_diagnosis", ["benign", None])
def test_pick_followup_plan_longer_when_previous_not_malignant(previous_diagnosis):
    rng = random.Random(0)
    for _ in range(20):
        assert pick_followup_plan(rng, previous_diagnosis) in FOLLOWUP_LONG_POOL


def test_deterministic_with_fixed_seed():
    seq1 = [pick_처방(random.Random(42), "benign") for _ in range(10)]
    seq2 = [pick_처방(random.Random(42), "benign") for _ in range(10)]
    assert seq1 == seq2
