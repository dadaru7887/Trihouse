"""Enforce the train/eval boundary by running the recipes and recording which
primitives actually execute, so a hidden dispatch cannot smuggle an effect in.

    pytest vision_ai/tests/worker/test_augmentation_holdout.py

Static import checks are not enough here: random_blur reaches disc_blur through
a dict lookup, which no import graph shows.
"""

from __future__ import annotations

import functools

import numpy as np
import pytest

from vision_ai.utils.augmentation import primitives as P
from vision_ai.utils.augmentation import scenarios as S

IMAGE = np.random.default_rng(0).integers(0, 255, (48, 64, 3), dtype=np.uint8)
DRAWS = 4           # recipes fix their settings, so a few draws cover every branch


@pytest.fixture
def atoms_used(monkeypatch):
    """Return a function that runs recipes and reports the primitives they ran."""
    hits: set[str] = set()

    def instrument():
        for name in dir(P):
            fn = getattr(P, name)
            if not callable(fn) or name.startswith("_"):
                continue
            if getattr(fn, "__module__", "") != P.__name__:
                continue

            def wrap(fn=fn, name=name):
                @functools.wraps(fn)
                def inner(*args, **kwargs):
                    hits.add(name)
                    return fn(*args, **kwargs)
                return inner

            wrapped = wrap()
            monkeypatch.setattr(P, name, wrapped)
            # scenarios.py imported these names, and recipe bodies resolve them
            # as module globals at call time, so patch that namespace too.
            if hasattr(S, name):
                monkeypatch.setattr(S, name, wrapped)
        # BLUR_FUNCS captured its values before patching.
        monkeypatch.setattr(P, "BLUR_FUNCS",
                            {k: getattr(P, v.__name__) for k, v in P.BLUR_FUNCS.items()})

    instrument()

    def run(recipes):
        hits.clear()
        S.configure_augmentation_seed(1)
        for recipe in recipes:
            for _ in range(DRAWS):
                recipe(IMAGE.copy())
        return set(hits)

    return run


def test_training_runs_only_the_atoms_it_is_allowed_to(atoms_used):
    """Nothing outside TRAIN_ATOMS may execute while training augments."""
    used = atoms_used(S.TRAIN_RECIPES)
    assert used - set(S.TRAIN_ATOMS) - set(S.UNTRACKED_ATOMS) == set()


@pytest.mark.parametrize("group", S.STRICTLY_UNSEEN_GROUPS)
def test_strictly_unseen_tiers_run_no_atom_training_ever_runs(group, atoms_used):
    """A scoring tier claiming 'unseen' must not touch a trained implementation."""
    used = atoms_used(S.recipes_in(group))
    leaked = used & set(S.TRAIN_ATOMS)
    assert not leaked, f"{group} scores with effects training also runs: {sorted(leaked)}"


def test_seen_compound_is_built_only_from_trained_effects(atoms_used):
    """The weak tier is exactly that: trained effects, new combination."""
    used = atoms_used(S.recipes_in("seen_compound"))
    assert used - set(S.TRAIN_ATOMS) == set()


@pytest.mark.parametrize("mechanism", S.MECHANISMS)
def test_holding_out_a_mechanism_removes_every_recipe_that_uses_it(mechanism, atoms_used):
    """No recipe left in the pool may reach the held-out mechanism's atoms."""
    used = atoms_used(S.pool_for(exclude={mechanism}))
    forbidden = used & set(S.ATOMS_OF_MECHANISM[mechanism])
    assert not forbidden, (
        f"--holdout {mechanism} left {sorted(forbidden)} in the training pool")


def test_every_recipe_id_is_unique():
    ids = [recipe.id for recipe in S.RECIPES]
    assert len(ids) == len(set(ids))


def test_training_and_evaluation_recipes_do_not_overlap():
    assert not {r.id for r in S.TRAIN_RECIPES} & {r.id for r in S.EVAL_RECIPES}


def test_every_group_has_recipes():
    for group in S.GROUPS:
        assert S.recipes_in(group), group


def test_mixed_augmentation_draws_every_training_recipe_about_equally():
    """Equal exposure per recipe, so no effect is starved by how groups are sized."""
    seen: dict[str, int] = {}
    for recipe in S.TRAIN_RECIPES:
        seen[recipe.id] = 0
    S.configure_augmentation_seed(7)
    S.configure_pool()
    picks = []
    original = S.random.choice

    def spy(pool):
        chosen = original(pool)
        picks.append(chosen.id)
        return chosen

    S.random.choice = spy
    try:
        for _ in range(1600):
            S.mixed_augmentation(IMAGE.copy())
    finally:
        S.random.choice = original

    counts = {rid: picks.count(rid) for rid in seen}
    expected = 1600 / len(S.TRAIN_RECIPES)
    assert min(counts.values()) > expected * 0.6, counts
    assert max(counts.values()) < expected * 1.4, counts
