"""Dead-cores cache - persistent skip list for refinement.

When a core expression exhausts its full Optuna refinement budget
(MAX_REFINEMENT_PER_CORE = 12 attempts) without producing any positive
score_change variant, it gets recorded here with a TTL.

The next time the same core surfaces (from gap_mining, signal_combo, LLM,
or any other generation path), the bot skips refinement entirely - saving
12 wasted sims per recurring dead core.

TTL is 48h by default so cores can re-enter the refinement pool eventually
in case the team's portfolio shifts enough to change their score_change.

Storage: simple JSON file at data/dead_cores.json. Atomic writes via
write-temp-then-rename. Tolerant of corruption - if the file is unreadable,
starts fresh.
"""

from __future__ import annotations

import json
import os
import time
import hashlib
from typing import Optional

import config


def _hash_core(core: str) -> str:
    """Stable hash for a core expression. Strips outer whitespace for safety."""
    canonical = (core or "").strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class DeadCoresCache:
    """Persistent set of core hashes with expiry timestamps."""

    def __init__(self, path: Optional[str] = None, ttl_sec: Optional[int] = None):
        self.path = path or getattr(config, "DEAD_CORES_CACHE_PATH", "data/dead_cores.json")
        self.ttl_sec = ttl_sec or getattr(config, "DEAD_CORES_TTL_SEC", 48 * 3600)
        # entries: hash -> {expires_at, core_preview, recorded_at}
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._entries = data.get("entries", {}) if "entries" in data else data
            self._prune_expired()
            print(f"[DEAD_CORES] Loaded {len(self._entries)} dead-core entries (TTL {self.ttl_sec // 3600}h)")
        except (json.JSONDecodeError, IOError, OSError) as exc:
            # corrupt or unreadable - start fresh, don't crash the bot
            print(f"[DEAD_CORES] Cache file unreadable ({exc!r}) - starting fresh")
            self._entries = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump({"entries": self._entries}, f, indent=1)
            os.replace(tmp_path, self.path)
        except (IOError, OSError) as exc:
            print(f"[DEAD_CORES] Failed to save cache ({exc!r}) - entries kept in memory")

    def _prune_expired(self) -> None:
        now = time.time()
        before = len(self._entries)
        self._entries = {
            h: meta for h, meta in self._entries.items()
            if isinstance(meta, dict) and meta.get("expires_at", 0) > now
        }
        if before != len(self._entries):
            self._save()

    def is_dead(self, core: str) -> bool:
        """Check whether a core should skip refinement."""
        if not core:
            return False
        h = _hash_core(core)
        meta = self._entries.get(h)
        if not meta:
            return False
        if meta.get("expires_at", 0) <= time.time():
            # expired - remove and let it through
            del self._entries[h]
            self._save()
            return False
        return True

    def mark_dead(self, core: str) -> None:
        """Record that a core exhausted refinement without a positive variant."""
        if not core:
            return
        h = _hash_core(core)
        now = time.time()
        self._entries[h] = {
            "expires_at": now + self.ttl_sec,
            "recorded_at": now,
            "core_preview": (core[:60] + "...") if len(core) > 60 else core,
        }
        self._save()

    def stats(self) -> dict:
        self._prune_expired()
        return {
            "active_entries": len(self._entries),
            "ttl_hours": self.ttl_sec // 3600,
        }


# module-level singleton - bot.py imports this and uses it directly
_cache_instance: Optional[DeadCoresCache] = None


def get_cache() -> DeadCoresCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DeadCoresCache()
    return _cache_instance
