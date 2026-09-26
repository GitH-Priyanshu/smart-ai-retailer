from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

class ContextStore:
    def __init__(self):
        # Key: (scope, context_id) -> {"version": int, "payload": dict, "delivered_at": str, "stored_at": str}
        self._store: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def push(
        self, scope: str, context_id: str, version: int, payload: Dict[str, Any], delivered_at: Optional[str] = None
    ) -> Tuple[bool, int, Dict[str, Any]]:
        """
        Pushes a context into the store with compare-and-replace semantics.
        Returns:
            (success: bool, http_status_code: int, response_dict: dict)
        """
        if scope not in VALID_SCOPES:
            return False, 400, {
                "accepted": False,
                "reason": "invalid_scope",
                "details": f"Scope '{scope}' is not valid. Must be one of: {sorted(list(VALID_SCOPES))}"
            }

        key = (scope, context_id)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        if key in self._store:
            current_version = self._store[key]["version"]
            if version <= current_version:
                return False, 409, {
                    "accepted": False,
                    "reason": "stale_version",
                    "current_version": current_version
                }

        # New context or higher version replacing atomically
        self._store[key] = {
            "version": version,
            "payload": payload,
            "delivered_at": delivered_at,
            "stored_at": now_iso
        }

        ack_id = f"ack_{context_id}_v{version}"
        return True, 200, {
            "accepted": True,
            "ack_id": ack_id,
            "stored_at": now_iso
        }

    def get(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        entry = self._store.get((scope, context_id))
        return entry["payload"] if entry else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        entry = self._store.get((scope, context_id))
        return entry["version"] if entry else None

    def get_counts(self) -> Dict[str, int]:
        counts = {s: 0 for s in VALID_SCOPES}
        for scope, _ in self._store.keys():
            counts[scope] += 1
        return counts

    def clear(self):
        self._store.clear()
