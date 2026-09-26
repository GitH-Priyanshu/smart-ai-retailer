from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ConversationStore:
    def __init__(self):
        # Key: conversation_id -> dict state
        self._conversations: Dict[str, Dict[str, Any]] = {}

    def get_or_create(
        self, conversation_id: str, merchant_id: Optional[str] = None, customer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = {
                "conversation_id": conversation_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "status": "active",
                "ended": False,
                "wait_until": None,
                "mode": "qualifying",  # "qualifying" | "action"
                "auto_reply_count": 0,
                "last_inbound_message": None,
                "last_bodies_sent": [],
                "turns": [],
            }
        else:
            if merchant_id and not self._conversations[conversation_id]["merchant_id"]:
                self._conversations[conversation_id]["merchant_id"] = merchant_id
            if customer_id and not self._conversations[conversation_id]["customer_id"]:
                self._conversations[conversation_id]["customer_id"] = customer_id
        return self._conversations[conversation_id]

    def record_turn(
        self,
        conversation_id: str,
        role: str,
        message: str,
        turn_number: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        conv = self.get_or_create(conversation_id)
        current_turns = conv["turns"]
        t_num = turn_number if turn_number is not None else (len(current_turns) + 1)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        turn_entry = {
            "turn_number": t_num,
            "role": role,
            "message": message,
            "timestamp": now_iso,
        }
        if extra:
            turn_entry.update(extra)

        current_turns.append(turn_entry)

        if role in ("vera", "merchant_on_behalf"):
            conv["last_bodies_sent"].append(message)
        elif role in ("merchant", "customer"):
            conv["last_inbound_message"] = message

        return turn_entry

    def get(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        return self._conversations.get(conversation_id)

    def get_turns(self, conversation_id: str) -> List[Dict[str, Any]]:
        conv = self._conversations.get(conversation_id)
        return conv["turns"] if conv else []

    def set_mode(self, conversation_id: str, mode: str):
        conv = self.get_or_create(conversation_id)
        conv["mode"] = mode

    def set_ended(self, conversation_id: str, ended: bool = True):
        conv = self.get_or_create(conversation_id)
        conv["ended"] = ended
        conv["status"] = "ended" if ended else "active"

    def set_wait(self, conversation_id: str, wait_seconds: int):
        conv = self.get_or_create(conversation_id)
        conv["status"] = "waiting"
        conv["wait_until"] = wait_seconds

    def clear(self):
        self._conversations.clear()
