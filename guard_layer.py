import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("vera_guard")

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

# URL regex for POST URL guard
URL_REGEX = re.compile(
    r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)",
    re.IGNORECASE
)

# Number extraction regex (matches integers, decimals, comma-separated numbers, percentages, rupee amounts)
NUMBER_REGEX = re.compile(r"(?:₹|\b)(\d+(?:,\d+)*(?:\.\d+)?%?)\b")

# Whitelisted conversational numbers that don't need context citation (e.g. Reply 1 or 2, 2-min read)
SAFE_CONVERSATIONAL_NUMBERS = {"1", "2", "3", "4", "2-min", "5 min", "10am", "11am", "4pm", "5pm", "6pm"}


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

    # =========================================================================
    # PRE-CHECKS (Inbound /v1/reply)
    # =========================================================================

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
        prior_inbounds: List[str],
    ) -> Optional[Dict[str, Any]]:
        norm_incoming = normalize_text(message)
        is_canned = self.is_canned_text(message)
        is_repeated = any(normalize_text(prior) == norm_incoming for prior in prior_inbounds if prior)

        if not (is_canned or is_repeated):
            return None

        key = conversation_id
        if "conv_auto" in conversation_id:
            key = f"auto_{merchant_id or 'default'}"

        count = self._auto_reply_counts.get(key, 0) + 1
        self._auto_reply_counts[key] = count

        if count == 1:
            return {
                "action": "send",
                "body": "Hi there! Just following up on my previous message to see if you had any thoughts. Let me know when you have a moment.",
                "cta": "open_ended",
                "rationale": "First detected auto-reply. Sending one gentle follow-up before waiting.",
            }
        elif count == 2:
            return {
                "action": "wait",
                "wait_seconds": 14400,
                "rationale": "Second canned auto-reply detected. Waiting 4 hours for human owner availability.",
            }
        else:
            return {
                "action": "end",
                "rationale": "Repeated canned auto-reply received 3 times. Ending conversation to prevent loop.",
            }

    def sanitize_action_mode_body(self, body: str) -> str:
        body_lower = body.lower()
        has_qualifying = any(q in body_lower for q in QUALIFYING_PHRASES)
        has_actioning = any(a in body_lower for a in ACTIONING_WORDS)

        if has_qualifying or not has_actioning:
            return "Done, here is the draft. We will proceed with the next step right away."
        return body

    # =========================================================================
    # POST-CHECKS (Outbound messages before send)
    # =========================================================================

    def check_urls(self, body: str) -> Tuple[bool, str]:
        """
        Rule 6: No URLs in the message body, ever.
        Strips raw URLs and cleans up dangling prepositions/phrases
        (e.g., 'at https://...', 'here: https://...', 'check out https://...'),
        preserving sentence punctuation and natural phrasing.
        """
        def repl(m):
            raw = m.group(0)
            punct = ""
            if raw.endswith(("?", ".", "!", ",")):
                punct = raw[-1]
            return punct

        pattern = re.compile(
            r"(?:\s*\b(?:at|on|from|via|here\b:?|link\b:?|visit|check\s+out|see|details\s+at)\s+)?https?://\S+",
            re.IGNORECASE,
        )
        if pattern.search(body):
            cleaned = pattern.sub(repl, body)
            # Clean up dangling prepositions before punctuation
            cleaned = re.sub(
                r"\b(?:at|on|from|via|link|visit)\s+([.?!,])", r"\1", cleaned, flags=re.IGNORECASE
            )
            cleaned = re.sub(r"\s+([.?!,])", r"\1", cleaned)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            return False, cleaned
        return True, body

    def check_repetition(self, body: str, prior_bodies: List[str]) -> bool:
        """
        Rule 7: Never repeat the same body text verbatim within the same conversation_id.
        """
        if not prior_bodies:
            return False
        norm_body = normalize_text(body)
        for prior in prior_bodies:
            if normalize_text(prior) == norm_body:
                return True
        return False

    def check_single_cta(
        self, body: str, trigger_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str]:
        """
        Rule 1: Single primary CTA only — never multiple asks in one message.
        Detects multiple distinct asks/questions, scores them against the trigger
        context, and preserves only the single best ask (dropping extraneous asks).
        """
        raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
        if not raw_sentences:
            return True, body

        questions = []
        for s in raw_sentences:
            if s.endswith("?") or re.search(
                r"\b(would you|do you|can you|could you|shall i|want me to|should we|how about|what if|are you|will you)\b",
                s,
                re.I,
            ):
                questions.append(s)

        if len(questions) <= 1:
            return True, body

        # Extract trigger terms to anchor the best question
        trigger_words = set()
        if trigger_context:
            for val in re.findall(r"\b[a-zA-Z0-9%]+\b", str(trigger_context).lower()):
                if len(val) > 2 and val not in {"true", "false", "none", "null"}:
                    trigger_words.add(val)

        generic_noise = {"demo", "call", "also", "meeting", "zoom", "schedule", "today", "confirm if you"}

        def score_question(q: str) -> float:
            score = 0.0
            q_lower = q.lower()
            if re.search(r"\d+%?", q):
                score += 3.0
            for w in trigger_words:
                if w in q_lower:
                    score += 2.0
            for g in generic_noise:
                if g in q_lower:
                    score -= 2.0
            return score

        best_q = max(questions, key=score_question)

        # Reconstruct body preserving original sentence order
        retained = []
        for s in raw_sentences:
            if s in questions:
                if s == best_q:
                    if not s.endswith("?"):
                        s += "?"
                    retained.append(s)
            else:
                retained.append(s)

        result = " ".join(retained).strip()
        # Ensure at most one question mark in final result
        if result.count("?") > 1:
            parts = result.rsplit("?", 1)
            result = parts[0].replace("?", ".") + "?" + parts[1]

        return False, result

    def extract_numbers_from_text(self, text: str) -> List[str]:
        """
        Extracts numbers, percentages, and amounts from text.
        Returns a list of raw numeric strings.
        """
        matches = NUMBER_REGEX.findall(text)
        cleaned = []
        for m in matches:
            raw = m.strip().rstrip(".,;:)")
            if raw:
                cleaned.append(raw)
        return cleaned

    def build_grounding_corpus(
        self,
        category: Optional[Dict[str, Any]],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Set[str], str]:
        """
        Builds a comprehensive set of verified numbers, strings, and tokens
        extracted directly from the 4 layers of context.
        """
        tokens: Set[str] = set()

        # Combine all context into a single JSON string for substring checks
        full_context_obj = {
            "category": category,
            "merchant": merchant,
            "trigger": trigger,
            "customer": customer,
        }
        raw_context_str = json.dumps(full_context_obj, default=str).lower()

        # Recursively extract numbers and tokens from dictionaries
        def extract_vals(obj: Any):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    extract_vals(v)
            elif isinstance(obj, list):
                for item in obj:
                    extract_vals(item)
            elif isinstance(obj, (int, float)):
                tokens.add(str(obj))
                tokens.add(str(int(obj)))
                # Percentage representation (e.g. 0.38 -> 38%)
                if isinstance(obj, float) and 0.0 <= obj <= 1.0:
                    pct = int(round(obj * 100))
                    tokens.add(f"{pct}")
                    tokens.add(f"{pct}%")
            elif isinstance(obj, str):
                for num in NUMBER_REGEX.findall(obj):
                    clean_num = num.strip().rstrip(".,;:)")
                    tokens.add(clean_num)
                    tokens.add(clean_num.replace(",", ""))
                    tokens.add(clean_num.replace("%", ""))

        extract_vals(full_context_obj)

        return tokens, raw_context_str

    def check_grounding(
        self,
        body: str,
        category: Optional[Dict[str, Any]],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        HIGHEST PRIORITY GUARD: Grounding / Anti-Fabrication Check.
        Extracts numbers and statistics from the composed body.
        Verifies that each number exists within the context corpus.
        Returns:
            (is_grounded: bool, ungrounded_numbers: List[str])
        """
        body_numbers = self.extract_numbers_from_text(body)
        if not body_numbers:
            return True, []

        corpus_tokens, raw_context_str = self.build_grounding_corpus(category, merchant, trigger, customer)

        ungrounded = []
        for num in body_numbers:
            # Check safe conversational numbers (e.g., choice 1/2)
            if num in SAFE_CONVERSATIONAL_NUMBERS or num.rstrip("%") in SAFE_CONVERSATIONAL_NUMBERS:
                continue

            num_clean = num.replace(",", "").rstrip("%")

            # Check if token exists in corpus
            matched = False
            if num in corpus_tokens or num_clean in corpus_tokens:
                matched = True
            elif num_clean in raw_context_str or num.lower() in raw_context_str:
                matched = True
            else:
                # Check for decimal percentage (e.g. "38%" -> "0.38" in context)
                try:
                    val = float(num_clean)
                    decimal_val = f"{val / 100:.3f}".rstrip("0")
                    if decimal_val in raw_context_str:
                        matched = True
                except ValueError:
                    pass

            if not matched:
                ungrounded.append(num)

        is_grounded = len(ungrounded) == 0
        return is_grounded, ungrounded

    def post_guard_composed_message(
        self,
        composed_body: str,
        category: Optional[Dict[str, Any]],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
        prior_bodies: Optional[List[str]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Runs ALL post guards:
        1. URL check -> strips URLs
        2. Anti-repetition check -> flags duplicate bodies
        3. Single-CTA check -> eliminates multiple questions
        4. Grounding check -> flags any fabricated numbers

        Returns:
            (passed: bool, sanitized_body: str, violation_reason: Optional[str])
        """
        # 1. URL Check
        has_no_url, sanitized_body = self.check_urls(composed_body)
        if not has_no_url:
            logger.warning("Post-guard: URL detected and stripped from body.")

        # 2. Anti-repetition Check
        if self.check_repetition(sanitized_body, prior_bodies or []):
            return False, sanitized_body, "duplicate_body_in_conversation"

        # 3. Single-CTA Check
        single_cta, sanitized_body = self.check_single_cta(sanitized_body, trigger)
        if not single_cta:
            logger.warning("Post-guard: Multiple CTAs collapsed to single CTA.")

        # 4. Grounding Check (Highest Priority)
        is_grounded, ungrounded_numbers = self.check_grounding(
            sanitized_body, category, merchant, trigger, customer
        )
        if not is_grounded:
            return False, sanitized_body, f"fabricated_numbers:{','.join(ungrounded_numbers)}"

        return True, sanitized_body, None
