"""Embedding-based tier classification for prompt routing."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Decision:
    tier: str
    margin: float
    escalated: bool


class Router:
    def __init__(
        self,
        centroids: dict[str, np.ndarray],
        capability_order: list[str],
        escalation_margin: float = 0.02,
    ):
        self.capability_order = capability_order
        self._margin = escalation_margin
        self._names = list(centroids)
        matrix = np.stack([np.asarray(centroids[n], dtype=float) for n in self._names])
        self._matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)

    def classify(self, vec: np.ndarray) -> Decision:
        v = np.asarray(vec, dtype=float)
        v = v / np.linalg.norm(v)
        sims = self._matrix @ v
        ranked = np.argsort(sims)
        margin = float(sims[ranked[-1]] - sims[ranked[-2]])
        tier = self._names[int(ranked[-1])]
        escalated = False
        # A thin margin means the classifier isn't sure; route one tier up.
        # Over-provisioning wastes cents, under-provisioning wastes an afternoon.
        rank = self.capability_order.index(tier)
        if margin < self._margin and rank < len(self.capability_order) - 1:
            tier = self.capability_order[rank + 1]
            escalated = True
        return Decision(tier=tier, margin=margin, escalated=escalated)
