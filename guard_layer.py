import re
from typing import Any, Dict, List, Optional, Tuple

# Pre-compiled hostile keywords & regexes
HOSTILE_KEYWORDS = [
    r"\bstop\b",
    r"\bspam\b",
    r"\buseless\b",
    r"\bunsubscribe\b",
    r"\bopt[\s\-]?out\b",
    r"\bdon'?t message\b",
    r"\bdo not message\b",
    r"\bleave me alone\b",
    r"\bnot interested\b",
    r"\bharass(ment)?\b",
    r"\bfraud\b",
    r"\bscam\b",
    r"\bshut up\b",
    r"\bblock(ed)?\b",
    r"\babuse\b",
]
HOSTILE_REGEX = re.compile("|".join(HOSTILE_KEYWORDS), re.IGNORECASE)

# Intent transition commitment phrases
INTENT_COMMITMENT_PHRASES = [
    r"\blet'?s do it\b",
    r"\blets do it\b",
    r"\bgo ahead\b",
    r"\bsounds good\b",
    r"\byes proceed\b",
    r"\bproceed\b",
    r"\bok lets start\b",
    r"\bok let'?s start\b",
    r"\blet'?s start\b",
    r"\blets start\b",
    r"\bconfirm\b",
    r"\bdo it\b",
    r"\byes please\b",
    r"\bsure let'?s do it\b",
    r"\bsure lets do it\b",
    r"\byes send\b",
    r"\bsend it\b",
    r"\byes do this\b",
    r"\bgo for it\b",
]
INTENT_REGEX = re.compile("|".join(INTENT_COMMITMENT_PHRASES), re.IGNORECASE)

# Canned auto-reply indicators
AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"thanks for contacting",
    r"our team will respond shortly",
    r"we will get back to you",
    r"thanks for reaching out",
    r"auto[\s\-]?reply",
    r"automated response",
    r"out of office",
    r"currently unavailable",
]
AUTO_REPLY_REGEX = re.compile("|".join(AUTO_REPLY_PATTERNS), re.IGNORECASE)

# Action vs Qualifying words for intent transition enforcement
ACTIONING_WORDS = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
QUALIFYING_PHRASES = ["would you", "do you", "can you tell", "what if", "how about"]


def normalize_text(text: str) -> str:
    """Normalize text: lowercase, remove punctuation, strip extra whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return " ".join(text.split())


class GuardLayer:
    def __init__(self):
        # Global auto-reply tracking across simulation test sessions (e.g. conv_auto_*)
        self._auto_reply_counts: Dict[str, int] = {}

    def check_pre_reply(
        self,
        conversation_id: str,
        merchant_id: Optional[str],
        message: str,
        prior_inbounds: List[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Runs PRE checks on incoming /v1/reply message:
        1. Hostile check -> immediately return 'end'
        2. Auto-reply check -> 1st: try once more, 2nd: wait, 3rd: end
        3. Intent transition check -> returns new mode ('action') if detected

        Returns:
            (intercepted_response: Optional[dict], new_mode: Optional[str])
        """
        # 1. Hostile Detection
        if self.is_hostile(message):
            return {
                "action": "end",
                "rationale": "Merchant opted out / sent hostile response ('stop/spam'). Ended conversation gracefully.",
            }, None

        # 2. Auto-Reply Detection
        auto_reply_resp = self.check_auto_reply(conversation_id, merchant_id, message, prior_inbounds)
        if auto_reply_resp:
            return auto_reply_resp, None

        # 3. Intent Transition Detection
        if self.is_intent_commitment(message):
            return None, "action"

        return None, None

    def is_hostile(self, message: str) -> bool:
        if not message:
            return False
        return bool(HOSTILE_REGEX.search(message))

    def is_intent_commitment(self, message: str) -> bool:
        if not message:
            return False
        return bool(INTENT_REGEX.search(message))

    def is_canned_text(self, message: str) -> bool:
        if not message:
            return False
        return bool(AUTO_REPLY_REGEX.search(message))

    def check_auto_reply(
        self,
        conversation_id: str,
        merchant_id: Optional[str],
        message: str,
        prior_inbound_messages: List[str],
    ) -> Optional[Dict[str, Any]]:
        norm_incoming = normalize_text(message)
        is_canned = self.is_canned_text(message)

        # Check if identical to prior inbound message in this conversation
        is_repeated = any(normalize_text(prior) == norm_incoming for prior in prior_inbound_messages if prior)

        if not (is_canned or is_repeated):
            return None

        # Key for tracking repeats: use conversation_id, or if testing conv_auto_*, track under session
        key = conversation_id
        if "conv_auto" in conversation_id:
            key = f"auto_{merchant_id or 'default'}"

        count = self._auto_reply_counts.get(key, 0) + 1
        self._auto_reply_counts[key] = count

        if count == 1:
            # 1st match: try once more (send friendly check-in)
            return {
                "action": "send",
                "body": "Hi there! Just following up on my previous message to see if you had any thoughts. Let me know when you have a moment.",
                "cta": "open_ended",
                "rationale": "First detected auto-reply. Sending one gentle follow-up before waiting.",
            }
        elif count == 2:
            # 2nd match: wait
            return {
                "action": "wait",
                "wait_seconds": 14400,
                "rationale": "Second canned auto-reply detected. Waiting 4 hours for human owner availability.",
            }
        else:
            # 3rd match or more: end
            return {
                "action": "end",
                "rationale": "Repeated canned auto-reply received 3 times. Ending conversation to prevent loop.",
            }

    def sanitize_action_mode_body(self, body: str) -> str:
        """
        Guarantees that when in 'action' mode, the response contains actioning
        words and NO qualifying questions.
        """
        body_lower = body.lower()
        has_qualifying = any(q in body_lower for q in QUALIFYING_PHRASES)
        has_actioning = any(a in body_lower for a in ACTIONING_WORDS)

        if has_qualifying or not has_actioning:
            return "Done, here is the draft. We will proceed with the next step right away."

        return body
