"""The recipe registry: tags, grouping, and what holdout removes.

Structural checks only. Whether holdout is leak-proof at runtime is
test_augmentation_holdout.py's job.

    pytest vision_ai/tests/worker/test_scenario_selection.py
"""

from __future__ import annotations

import numpy as np
import pytest

from vision_ai.utils.augmentation import scenarios


def test_every_recipe_names_a_known_mechanism_and_group():
    """An unknown tag would make the recipe invisible to holdout."""
    for recipe in scenarios.RECIPES:
        assert recipe.group in scenarios.GROUPS, recipe.id
        # Compounds name several mechanisms joined by '+'.
        for mechanism in recipe.mechanism.split("+"):
            assert mechanism in scenarios.ATOMS_OF_MECHANISM, recipe.id


def test_training_recipes_are_single_mechanism():
    """A training recipe mixing effects would make holdout ambiguous."""
    for recipe in scenarios.TRAIN_RECIPES:
        assert "+" not in recipe.mechanism, recipe.id
        assert recipe.mechanism in scenarios.MECHANISMS, recipe.id


def test_the_training_groups_hold_the_documented_counts():
    """Pin the pool size; a recipe added or lost changes every exposure rate."""
    counts = {group: len(scenarios.recipes_in(group)) for group in scenarios.SCENARIOS}
    assert counts == {"S1": 4, "S2": 5, "S3": 5, "S4": 2}
    assert len(scenarios.TRAIN_RECIPES) == 16


def test_holding_out_a_mechanism_removes_exactly_its_recipes():
    """Holdout must drop the mechanism's recipes and nothing else."""
    pool = scenarios.pool_for(exclude={"condensation"})
    assert not [r for r in pool if r.mechanism == "condensation"]
    assert len(pool) == len(scenarios.TRAIN_RECIPES) - 5


def test_holding_out_nothing_returns_every_training_recipe():
    """The default run trains on the whole pool."""
    assert scenarios.pool_for(exclude=set()) == list(scenarios.TRAIN_RECIPES)


def test_holding_out_an_unknown_mechanism_is_refused():
    """A typo must fail loudly, not silently train on everything."""
    with pytest.raises(ValueError, match="unknown mechanism"):
        scenarios.pool_for(exclude={"snow"})


def test_holding_out_everything_is_refused():
    """An empty pool would train with no augmentation while claiming to."""
    with pytest.raises(ValueError, match="empty pool"):
        scenarios.pool_for(exclude=set(scenarios.MECHANISMS))


def test_a_single_recipe_can_be_applied_for_evaluation():
    """Per-recipe scoring needs one recipe addressable by id."""
    image = np.random.default_rng(0).integers(0, 255, (48, 64, 3), dtype=np.uint8)
    scenarios.configure_augmentation_seed(42)
    out = scenarios.apply_recipe(image, "S4_frost_thick")
    assert out.shape == image.shape
    assert out.dtype == image.dtype
    assert not np.array_equal(out, image)


def test_applying_an_unknown_recipe_is_refused():
    """A mistyped id must not silently score an unaugmented split."""
    image = np.zeros((10, 10, 3), dtype="uint8")
    with pytest.raises(ValueError, match="unknown recipe"):
        scenarios.apply_recipe(image, "S9_nonsense")


def test_applying_an_unknown_group_is_refused():
    """Same for a group name."""
    image = np.zeros((10, 10, 3), dtype="uint8")
    with pytest.raises(ValueError, match="unknown group"):
        scenarios.apply_group(image, "S9")


def test_a_compound_is_built_from_the_training_recipes_it_names():
    """Editing a training recipe must change every compound that uses it.

    Compounds that copied their parameters instead would silently drift.
    """
    image = np.random.default_rng(1).integers(0, 255, (48, 64, 3), dtype=np.uint8)
    original = scenarios._TRAIN_BY_ID["S4_frost_thick"].apply

    scenarios.configure_augmentation_seed(3)
    before = scenarios.apply_recipe(image, "C_lowlight_frost_strong")
    try:
        # Swap the training recipe body for a no-op.
        object.__setattr__(scenarios._TRAIN_BY_ID["S4_frost_thick"], "apply",
                           lambda img: img)
        scenarios.configure_augmentation_seed(3)
        after = scenarios.apply_recipe(image, "C_lowlight_frost_strong")
    finally:
        object.__setattr__(scenarios._TRAIN_BY_ID["S4_frost_thick"], "apply", original)

    assert not np.array_equal(before, after)


def test_seen_compounds_only_name_training_recipes():
    """The weak tier is defined by using trained mechanisms only."""
    for recipe in scenarios.recipes_in("seen_compound"):
        for mechanism in recipe.mechanism.split("+"):
            assert mechanism in scenarios.MECHANISMS, recipe.id


def test_unseen_compounds_only_name_unseen_recipes():
    """The strict tier must stay free of anything training runs."""
    unseen = {r.mechanism for r in scenarios.recipes_in("unseen")}
    for recipe in scenarios.recipes_in("unseen_compound"):
        for mechanism in recipe.mechanism.split("+"):
            assert mechanism in unseen, recipe.id
