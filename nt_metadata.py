"""Offline algorithm metadata store for Disting NT.

Loads bundled algorithm data from data/nt_algorithms.json and provides
lookup-by-GUID, lookup-by-name, and scored fuzzy search — all using stdlib only.
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path


class NTMetadataStore:
    """In-memory store for Disting NT algorithm metadata."""

    def __init__(self) -> None:
        self._algorithms: list[dict] = []
        self._by_guid: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}  # lowercase name → algo

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, path: str | Path | None = None) -> None:
        """Load algorithm metadata from JSON file.

        Args:
            path: Path to nt_algorithms.json.  Defaults to data/nt_algorithms.json
                  relative to this module's directory.
        """
        if path is None:
            path = Path(__file__).parent / "data" / "nt_algorithms.json"
        else:
            path = Path(path)

        with open(path) as f:
            self._algorithms = json.load(f)

        self._by_guid = {a["guid"]: a for a in self._algorithms}
        self._by_name = {a["name"].lower(): a for a in self._algorithms}

    @property
    def count(self) -> int:
        return len(self._algorithms)

    # ------------------------------------------------------------------
    # Exact lookup
    # ------------------------------------------------------------------

    def get(self, identifier: str) -> dict | None:
        """Look up an algorithm by GUID (exact) or name (case-insensitive).

        Returns the full algorithm dict, or None if not found.
        """
        # Try GUID first (always lowercase 4-char)
        result = self._by_guid.get(identifier.lower())
        if result:
            return result
        # Try exact name (case-insensitive)
        return self._by_name.get(identifier.lower())

    # ------------------------------------------------------------------
    # Fuzzy search
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Fuzzy search over all algorithms.

        Returns a list of dicts with keys: guid, name, score, categories,
        short_description, num_parameters, num_inputs, num_outputs.
        Sorted by descending score.
        """
        if not self._algorithms:
            return []

        q = query.lower().strip()
        if not q:
            return []

        scored: list[tuple[float, dict]] = []

        for algo in self._algorithms:
            score = self._score(q, algo)
            if score > 0:
                scored.append((score, algo))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, algo in scored[:max_results]:
            results.append({
                "guid": algo["guid"],
                "name": algo["name"],
                "score": round(score, 1),
                "categories": algo.get("categories", []),
                "short_description": algo.get("short_description", ""),
                "num_parameters": len(algo.get("parameters", [])),
                "num_inputs": len(algo.get("input_ports", [])),
                "num_outputs": len(algo.get("output_ports", [])),
            })

        return results

    @staticmethod
    def _score(query: str, algo: dict) -> float:
        """Score an algorithm against a search query."""
        score = 0.0
        name_lower = algo["name"].lower()

        # Exact name match
        if query == name_lower:
            return 100.0

        # Name contains query
        if query in name_lower:
            score = max(score, 50.0)

        # Fuzzy name match
        ratio = SequenceMatcher(None, query, name_lower).ratio()
        if ratio > 0.6:
            score = max(score, ratio * 80)

        # GUID match
        guid = algo.get("guid", "").lower()
        if query == guid:
            score = max(score, 90.0)
        elif query in guid:
            score = max(score, 40.0)

        # Category substring
        for cat in algo.get("categories", []):
            if query in cat.lower():
                score += 20.0
                break

        # Description substring
        desc = algo.get("description", "").lower()
        if query in desc:
            score += 15.0

        # Parameter name substring
        for param in algo.get("parameters", []):
            if query in param.get("name", "").lower():
                score += 10.0
                break

        # Use case substring
        for uc in algo.get("use_cases", []):
            if query in uc.lower():
                score += 10.0
                break

        return score
