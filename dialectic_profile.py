from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DialecticDimension:
    key: str
    left_label: str
    right_label: str
    score: float = 0.0          # -1.0 (left) .. +1.0 (right)
    confidence: float = 0.5     # 0.0 .. 1.0
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class DialecticProfile:
    dimensions: dict[str, DialecticDimension] = field(default_factory=dict)
    notes: str = ""
    updated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: str, limit: int = 240) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 3)].rstrip() + "..."


class DialecticProfileManager:
    """Honcho-style dialectic user profile with explicit tradeoff dimensions."""

    DEFAULT_DIMENSIONS: dict[str, tuple[str, str]] = {
        "speed_vs_quality": ("speed", "quality"),
        "autonomy_vs_control": ("autonomy", "control"),
        "brevity_vs_depth": ("brevity", "depth"),
        "innovation_vs_stability": ("innovation", "stability"),
        "risk_acceptance_vs_safety": ("risk_acceptance", "safety"),
    }

    _POSITIVE_HINTS: dict[str, list[str]] = {
        "speed_vs_quality": ["ship fast", "quickly", "fast", "velocity", "urgent", "now"],
        "autonomy_vs_control": ["you decide", "autonomous", "take ownership", "run with it"],
        "brevity_vs_depth": ["concise", "short", "brief", "tl;dr"],
        "innovation_vs_stability": ["innovate", "experiment", "new approach", "creative", "bold"],
        "risk_acceptance_vs_safety": ["aggressive", "move fast", "accept risk", "tradeoff"],
    }
    _NEGATIVE_HINTS: dict[str, list[str]] = {
        "speed_vs_quality": ["high quality", "quality first", "robust", "thorough", "careful"],
        "autonomy_vs_control": ["approval", "check with me", "confirm first", "manual review"],
        "brevity_vs_depth": ["detailed", "deep dive", "comprehensive", "explain fully"],
        "innovation_vs_stability": ["stable", "predictable", "proven", "minimal change", "conservative"],
        "risk_acceptance_vs_safety": ["safe", "safety", "low risk", "avoid risk", "guardrail"],
    }

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root

    @property
    def path(self) -> Path:
        return Path(self.workspace_root) / ".tau" / "assistant" / "dialectic_profile.json"

    def _build_default(self) -> DialecticProfile:
        dims: dict[str, DialecticDimension] = {}
        for key, (left, right) in self.DEFAULT_DIMENSIONS.items():
            dims[key] = DialecticDimension(
                key=key,
                left_label=left,
                right_label=right,
                score=0.0,
                confidence=0.5,
                rationale="Default neutral prior.",
                evidence=[],
                updated_at=_now_iso(),
            )
        return DialecticProfile(dimensions=dims, notes="", updated_at=_now_iso())

    def load(self) -> DialecticProfile:
        if not self.path.exists():
            return self._build_default()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            dims: dict[str, DialecticDimension] = {}
            for key, (left, right) in self.DEFAULT_DIMENSIONS.items():
                src = raw.get("dimensions", {}).get(key, {})
                dims[key] = DialecticDimension(
                    key=key,
                    left_label=str(src.get("left_label", left)),
                    right_label=str(src.get("right_label", right)),
                    score=float(src.get("score", 0.0)),
                    confidence=float(src.get("confidence", 0.5)),
                    rationale=str(src.get("rationale", "")),
                    evidence=[str(x) for x in src.get("evidence", []) if str(x).strip()],
                    updated_at=str(src.get("updated_at", "")) or _now_iso(),
                )
            return DialecticProfile(
                dimensions=dims,
                notes=str(raw.get("notes", "")),
                updated_at=str(raw.get("updated_at", "")) or _now_iso(),
            )
        except Exception:
            return self._build_default()

    def save(self, profile: DialecticProfile) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dimensions": {k: asdict(v) for k, v in profile.dimensions.items()},
            "notes": profile.notes,
            "updated_at": _now_iso(),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(self.path)

    def as_dict(self, profile: DialecticProfile) -> dict[str, Any]:
        return {
            "dimensions": {k: asdict(v) for k, v in profile.dimensions.items()},
            "notes": profile.notes,
            "updated_at": profile.updated_at,
            "path": str(self.path),
        }

    def update_dimension(
        self,
        *,
        key: str,
        score: float,
        confidence: float,
        rationale: str = "",
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        prof = self.load()
        dim = prof.dimensions.get(key)
        if dim is None:
            raise ValueError(f"Unknown dialectic dimension: {key}")
        dim.score = max(-1.0, min(1.0, float(score)))
        dim.confidence = max(0.0, min(1.0, float(confidence)))
        dim.rationale = rationale.strip() or dim.rationale
        dim.updated_at = _now_iso()
        if evidence:
            merged = dim.evidence + [str(x).strip() for x in evidence if str(x).strip()]
            # keep unique while preserving order
            seen: set[str] = set()
            deduped: list[str] = []
            for item in merged:
                if item in seen:
                    continue
                seen.add(item)
                deduped.append(_clip(item, 260))
            dim.evidence = deduped[-12:]
        prof.updated_at = _now_iso()
        path = self.save(prof)
        return {"key": key, "dimension": asdict(dim), "path": path}

    @staticmethod
    def _count_matches(text: str, hints: list[str]) -> int:
        low = text.lower()
        return sum(1 for h in hints if h in low)

    def infer(
        self,
        *,
        evidence_text: str,
        notes: str = "",
    ) -> dict[str, Any]:
        prof = self.load()
        text = re.sub(r"\s+", " ", evidence_text.strip())
        if not text:
            return {"updated": False, "reason": "empty_evidence", "profile": self.as_dict(prof)}

        for key in self.DEFAULT_DIMENSIONS:
            dim = prof.dimensions[key]
            pos = self._count_matches(text, self._POSITIVE_HINTS.get(key, []))
            neg = self._count_matches(text, self._NEGATIVE_HINTS.get(key, []))
            total = pos + neg
            if total == 0:
                continue
            raw_score = (pos - neg) / float(total)
            # Smooth toward previous score to avoid oscillation.
            dim.score = max(-1.0, min(1.0, (dim.score * 0.4) + (raw_score * 0.6)))
            dim.confidence = max(dim.confidence, min(1.0, 0.35 + (0.15 * total)))
            dim.rationale = f"Inferred from linguistic evidence (pos={pos}, neg={neg})."
            dim.evidence = (dim.evidence + [_clip(text, 260)])[-12:]
            dim.updated_at = _now_iso()

        if notes.strip():
            prof.notes = _clip(notes.strip(), 1200)
        prof.updated_at = _now_iso()
        path = self.save(prof)
        return {"updated": True, "path": path, "profile": self.as_dict(prof)}
