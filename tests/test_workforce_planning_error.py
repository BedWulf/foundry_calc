"""Regression test: failed molding planning must not yield invented staff numbers."""
from core.project import Project
from core.casting_item import CastingItem
from core.workforce import calc_workforce


def test_workforce_blocked_after_molding_planning_error():
    project = Project()
    project.castings = [CastingItem(name="Test", annual_qty_pcs=10,
                                   molds_per_year=10, mass_with_LPS_kg=1)]
    result = calc_workforce(project, molding={
        "batch_planning_error": "Invalid flask dimensions",
        "line_count": 1,
    })
    assert result.complete is False
    assert not result.rows
