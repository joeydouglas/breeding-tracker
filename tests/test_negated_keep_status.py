"""Regression: negated "keep" must not be parsed as a keeper signal (MSU07)."""
import pytest

from breeding_tracker import breeding_core as core


@pytest.mark.parametrize("text", [
    "MSU 07 is fine for a sativa. It's kind of weak. I don't wanna keep working with it.",
    "I won't keep this one.",
    "Not gonna keep it, too sleepy.",
    "never keep this pheno",
    "I do not want to keep it",
])
def test_negated_keep_is_not_keeper(text):
    assert core.parse_observation(text).get('status') is None


@pytest.mark.parametrize("text", [
    "I'll keep it for now but I probably shouldn't.",
    "We'll keep this one for now.",
    "Total keeper!",
    "definitely a keeper",
])
def test_positive_keep_is_still_keeper(text):
    assert core.parse_observation(text)['status'] == 'keeper'


def test_negated_keep_with_cull_still_culled():
    assert core.parse_observation("don't wanna keep it. culled.")['status'] == 'culled'
