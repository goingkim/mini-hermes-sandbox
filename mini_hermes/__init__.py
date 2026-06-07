"""Research-sized Hermes-style agent.

The package keeps the core Hermes ideas small enough to inspect:
provider selection, tool registry, tool-calling loop, persistent memory,
screen observations, scheduler, trajectories, and display video dataset episodes.
"""

__all__ = ["MiniHermesAgent", "MiniHermesStore", "RunResult"]


def __getattr__(name: str) -> object:
    if name in {"MiniHermesAgent", "RunResult"}:
        from mini_hermes.agent import MiniHermesAgent, RunResult

        return {"MiniHermesAgent": MiniHermesAgent, "RunResult": RunResult}[name]
    if name == "MiniHermesStore":
        from mini_hermes.store import MiniHermesStore

        return MiniHermesStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
