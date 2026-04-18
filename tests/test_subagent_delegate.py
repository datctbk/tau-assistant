from __future__ import annotations

from subagent_delegate import load_tau_agents_personas


def test_load_tau_agents_personas():
    personas = load_tau_agents_personas()
    # If tau-agents package exists in this monorepo, these built-ins should be available.
    assert "explore" in personas
    assert "plan" in personas
    assert "verify" in personas
    assert personas["explore"].max_turns >= 1
