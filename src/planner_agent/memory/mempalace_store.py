"""MemPalaceStore — semantic memory wrapper around MemPalace/ChromaDB.

Replaces the flat MEMORY.md append pattern with semantic search + storage.
Uses mempalace's function-based API for storing and searching memories.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Hall types — maps to MemPalace's built-in hall structure
HALL_FACTS = "hall_facts"
HALL_EVENTS = "hall_events"
HALL_PREFERENCES = "hall_prefs"
HALL_ADVICE = "hall_advice"

DEFAULT_WING = "wing_me"


class MemPalaceStore:
    """Thin wrapper around MemPalace's Python API.

    Lazily imports MemPalace on first use so the rest of the app can
    start even if ChromaDB is not installed (graceful degradation).

    Args:
        palace_path: Directory where ChromaDB + KG files are stored.
    """

    def __init__(self, palace_path: Path) -> None:
        self._palace_path = palace_path
        self._palace_path.mkdir(parents=True, exist_ok=True)
        self._palace_str = str(palace_path)
        self._wing = DEFAULT_WING
        self._initialised = False
        self._collection = None

    def _ensure_init(self) -> None:
        """Lazy-import MemPalace so startup isn't blocked by ChromaDB."""
        if self._initialised:
            return
        try:
            from mempalace.palace import get_collection

            self._collection = get_collection(self._palace_str)
        except ModuleNotFoundError:
            raise ImportError(
                "MemPalace not installed. Run: poetry add mempalace chromadb"
            )
        self._initialised = True

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = 3,
        hall: str | None = None,
    ) -> list[str]:
        """Semantic search across stored memories.

        Args:
            query: Natural-language query.
            n_results: Max snippets to return (keep 3-5 for cost).
            hall: Optional hall filter.

        Returns:
            List of relevant text snippets (may be empty on error).
        """
        self._ensure_init()
        try:
            from mempalace.searcher import search_memories

            where: dict = {"wing": self._wing}
            if hall:
                where["hall"] = hall

            results = search_memories(
                query=query,
                n_results=n_results,
                palace_path=self._palace_str,
                where=where,
            )
            return [r.get("document", "") for r in results if r.get("document")]
        except Exception as e:
            logger.warning("MemPalace search failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(
        self,
        text: str,
        hall: str = HALL_EVENTS,
        room: str | None = None,
    ) -> None:
        """Store a memory verbatim (raw mode for best recall).

        Args:
            text: The text to persist.
            hall: Hall to file under.
            room: Optional room name.
        """
        self._ensure_init()
        try:
            doc_id = hashlib.sha256(text.encode()).hexdigest()[:16]
            metadata: dict = {
                "wing": self._wing,
                "hall": hall,
                "date": date.today().isoformat(),
            }
            if room:
                metadata["room"] = room

            self._collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata],
            )
            logger.info(
                "MemPalace stored (%s/%s): %s…",
                hall,
                room or "—",
                text[:60],
            )
        except Exception as e:
            logger.warning("MemPalace store failed: %s", e)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def store_reflection(self, summary: str) -> None:
        """Store an evening reflection summary."""
        dated = f"[{date.today().isoformat()}] {summary}"
        self.store(dated, hall=HALL_EVENTS, room="daily-reflection")

    def store_goal_update(self, note: str) -> None:
        """Store a goal progress note."""
        dated = f"[{date.today().isoformat()}] {note}"
        self.store(dated, hall=HALL_FACTS, room="goal-progress")

    def store_preference(self, note: str) -> None:
        """Store a preference or habit note."""
        self.store(note, hall=HALL_PREFERENCES, room="habits")

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_for_prompt(snippets: list[str]) -> str:
        """Format search results for injection into the system prompt."""
        if not snippets:
            return "(No relevant memories found)"
        lines = [f"- {s.strip()}" for s in snippets if s.strip()]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Debugging / introspection
    # ------------------------------------------------------------------

    def list_all(self) -> list[dict]:
        """Return all stored memories with metadata (for debugging).

        Returns:
            List of dicts with ``id``, ``text``, ``hall``, ``room``,
            and ``date`` keys.
        """
        self._ensure_init()
        try:
            results = self._collection.get(include=["documents", "metadatas"])
            entries: list[dict] = []
            for doc_id, doc, meta in zip(
                results["ids"], results["documents"], results["metadatas"]
            ):
                entries.append({
                    "id": doc_id,
                    "text": doc,
                    "hall": meta.get("hall", "?"),
                    "room": meta.get("room", "?"),
                    "date": meta.get("date", "?"),
                })
            return entries
        except Exception as e:
            logger.warning("MemPalace list_all failed: %s", e)
            return []

    def format_listing(self, query: str | None = None, max_preview: int = 80) -> str:
        """Human-readable dump of memories (for /memories command).

        Args:
            query: Optional filter — matches against hall, room, date,
                or text content (case-insensitive substring).
            max_preview: Max characters of text shown per entry.

        Returns:
            Formatted string ready to send to the user.
        """
        entries = self.list_all()
        if not entries:
            return "🧠 MemPalace is empty — no memories stored yet."

        if query:
            q = query.lower()
            entries = [
                e for e in entries
                if q in e["hall"].lower()
                or q in e["room"].lower()
                or q in e["date"].lower()
                or q in e["text"].lower()
            ]

        if not entries:
            return f"🧠 No memories matching '{query}'."

        header = f"🧠 MemPalace — {len(entries)} memories"
        if query:
            header += f" matching '{query}'"
        lines = [header + "\n"]
        for i, e in enumerate(entries, 1):
            preview = e["text"][:max_preview].replace("\n", " ")
            lines.append(
                f"{i:2}. [{e['hall']}/{e['room']}] ({e['date']})\n"
                f"    {preview}…"
            )
        return "\n".join(lines)

