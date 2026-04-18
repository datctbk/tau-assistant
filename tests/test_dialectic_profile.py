from __future__ import annotations

from dialectic_profile import DialecticProfileManager


def test_dialectic_profile_update_and_infer(tmp_path):
    mgr = DialecticProfileManager(str(tmp_path))
    updated = mgr.update_dimension(
        key="brevity_vs_depth",
        score=-0.4,
        confidence=0.8,
        rationale="Prefers detailed explanations",
        evidence=["deep dive requested"],
    )
    assert updated["key"] == "brevity_vs_depth"
    assert updated["dimension"]["score"] < 0

    inferred = mgr.infer(
        evidence_text="Please keep responses concise and brief. Also avoid risk and prefer safe rollout.",
        notes="auto inference run",
    )
    assert inferred["updated"] is True
    dims = inferred["profile"]["dimensions"]
    assert dims["brevity_vs_depth"]["score"] >= 0
    assert dims["risk_acceptance_vs_safety"]["score"] <= 0
