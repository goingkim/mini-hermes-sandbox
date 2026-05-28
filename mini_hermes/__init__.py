"""Research-sized Hermes-style agent.

The package keeps the core Hermes ideas small enough to inspect:
provider selection, tool registry, tool-calling loop, persistent memory,
screen observations, scheduler, trajectories, and Windows interaction episodes.
"""

from mini_hermes.agent import MiniHermesAgent, RunResult
from mini_hermes.store import MiniHermesStore

__all__ = ["MiniHermesAgent", "MiniHermesStore", "RunResult"]
