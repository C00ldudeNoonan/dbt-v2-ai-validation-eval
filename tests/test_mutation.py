import pytest

from harness.common import PROJECT_DIR
from harness.mutate import CONTROL, Edit, MutationError, Variant, all_variants, apply_edits, apply_variant


def test_apply_edits_requires_exactly_one_match():
    assert apply_edits("a b c", [Edit("b", "B")], "x") == "a B c"
    with pytest.raises(MutationError):
        apply_edits("a b b", [Edit("b", "B")], "x")
    with pytest.raises(MutationError):
        apply_edits("a c", [Edit("b", "B")], "x")


def test_every_catalog_mutation_applies_to_the_golden_project(tmp_path):
    variants = all_variants()
    assert len({v.variant_id for v in variants}) == len(variants)
    for v in variants:
        proj = tmp_path / v.variant_id
        (proj / "models/marts/metrics").mkdir(parents=True)
        for ext in ("sql", "yml"):
            src = PROJECT_DIR / f"models/marts/metrics/{v.task}.{ext}"
            (proj / f"models/marts/metrics/{v.task}.{ext}").write_text(src.read_text())
        before = (proj / v.target_file).read_text()
        apply_variant(v, proj)
        after = (proj / v.target_file).read_text()
        assert (before == after) == v.is_control, v.variant_id
        v.reference_query()  # reference overrides apply cleanly


def test_controls_exist_for_every_task():
    from harness.common import tasks
    controls = {v.task for v in all_variants() if v.fault_id == CONTROL}
    assert controls == set(tasks())


def test_mutation_cannot_touch_other_models(tmp_path):
    v = Variant("t__X", "daily_order_counts", "X",
                edits=[Edit("a", "b", file="models/marts/metrics/monthly_active_customers.sql")])
    with pytest.raises(MutationError):
        apply_variant(v, tmp_path)


def test_shared_def_overrides_reference_only_for_that_variant():
    vs = {v.variant_id: v for v in all_variants()}
    shared = vs["monthly_revenue_by_location__F-SHARED-DEF"].reference_query()
    control = vs["monthly_revenue_by_location__CONTROL"].reference_query()
    assert "raw_refunds" in control and "raw_refunds" not in shared
    assert "raw_refunds" in vs["monthly_revenue_by_location__F-FILTER"].reference_query()
