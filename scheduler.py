from __future__ import annotations


class Scheduler:
    def __init__(self, max_slots: int = 3):
        self.max_slots = max_slots
        self.running: dict[str, str] = {}  # sim_id -> run_id

    def has_capacity(self) -> bool:
        return len(self.running) < self.max_slots

    def add(self, sim_id: str, run_id: str) -> None:
        self.running[sim_id] = run_id

    def remove(self, sim_id: str) -> None:
        self.running.pop(sim_id, None)

    def get_run_id(self, sim_id: str) -> str | None:
        return self.running.get(sim_id)

    def active_items(self) -> list[tuple[str, str]]:
        return list(self.running.items())

    def active_count(self) -> int:
        return len(self.running)

    def is_running(self, sim_id: str) -> bool:
        return sim_id in self.running
