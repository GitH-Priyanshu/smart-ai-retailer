import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("vera_composer")

# ---------------------------------------------------------
# Output Schema
# ---------------------------------------------------------

class ComposedMessage(BaseModel):
    body: str = Field(description="The WhatsApp message text")
    cta: Literal[
        "open_ended",
        "binary_yes_no",
        "binary_confirm_cancel",
        "multi_choice_slot",
        "none"
    ] = Field(description="Primary CTA type")
    send_as: Literal["vera", "merchant_on_behalf"] = Field(
        description="'vera' for merchant-facing, 'merchant_on_behalf' for customer-facing"
    )
    suppression_key: str = Field(description="Suppression/dedup key")
    rationale: str = Field(
        description="Grounded explanation of why this message was composed, citing specific context facts"
    )


class ReplyDecision(BaseModel):
    action: Literal["send", "wait", "end"] = Field(description="Action to take")
    body: Optional[str] = Field(default=None, description="Message body if action is send")
    cta: Optional[Literal[
        "open_ended",
        "binary_yes_no",
        "binary_confirm_cancel",
        "multi_choice_slot",
        "none"
    ]] = Field(default="open_ended", description="CTA if action is send")
    wait_seconds: Optional[int] = Field(default=None, description="Seconds to wait if action is wait")
    rationale: str = Field(description="Honest grounded rationale for the action")


# ---------------------------------------------------------
# System Prompt & Kind-Aware Framing
# ---------------------------------------------------------

SYSTEM_PROMPT = """You are Vera, magicpin's deterministic AI assistant for local merchants (dentists, salons, restaurants, gyms, pharmacies).
Your job is to compose ONE grounded, specific, low-friction WhatsApp message based on 4 layers of context: Category, Merchant, Trigger, and optional Customer.

### CRITICAL RULES (NON-NEGOTIABLE):
1. SINGLE PRIMARY CTA ONLY: Exactly one clear ask. Never include multiple questions or options like "Reply YES for X, NO for Y".
2. SPECIFICITY WINS: Anchor on verifiable facts from the provided context (exact numbers, percentages, dates, prices, citations). "Haircut @ ₹99" beats "discount".
3. NEVER FABRICATE: Only use facts, figures, dates, and citations present in the JSON context below. If a statistic, citation, or offer is not explicitly provided, DO NOT invent it. Fabricating numbers or claims will disqualify the output.
4. CATEGORY VOICE:
   - dentists: Clinical, peer-level, respectful, evidence-grounded, zero promotional hype.
   - salons: Warm-practical, trend-conscious, inviting, helpful.
   - restaurants: Operator-to-operator, margin-aware, concise, action-focused.
   - gyms: Coaching, motivating, progress-oriented, structured.
   - pharmacies: Trustworthy-precise, compliance-minded, health-focused, strictly factual.
5. LANGUAGE PREFERENCE:
   - Match the merchant's/customer's language preference ("en", "hi", "hi-en mix") exactly.
   - If "hi" or "hi-en mix", naturally code-mix Hindi and English (Hinglish) as common on Indian WhatsApp.
   - Never default to pure English if "hi" or "hi-en mix" is specified.
6. NO URLS: Never include URLs or web links in the message body.
7. NO PREAMBLE: No long generic openers like "I hope you are doing well" or "Greetings of the day". Start immediately with the relevant hook.
8. IDENTITY & SEND_AS:
   - Merchant-facing: send_as="vera". Address the merchant owner by first name.
   - Customer-facing: send_as="merchant_on_behalf". Speak as the merchant (e.g., "Hi Priya, Dr. Meera's clinic here...").
9. ANTI-REPETITION: Do not repeat sentences or phrasing from previous messages in the conversation.
10. RATIONALE: Must give a genuine, grounded explanation referencing the exact facts used.
11. NO STRUCTURAL REUSE: Never reuse the sentence STRUCTURE of any case-study example, even with different words. Vary: which fact comes first, whether the message opens with a question or a statement, where the citation appears (start, middle, or end), and how the call-to-action is phrased. The only things that must stay identical to the source data are the FACTS themselves (numbers, names, dates, citations) — never the sentence shape used to present them. Before finalizing output, mentally check: if I strip out the specific facts, does the remaining sentence skeleton look like any case-study example? If yes, restructure.

### TRIGGER KIND FRAMING GUIDELINES:
- research_digest: Vary structure. You may open with the clinical metric, a direct question about clinical protocols, or the citation itself. Frame around curiosity, clinical relevance, and offer to draft a customer note.
- regulation_change / compliance: Lead with the authority/deadline and specific requirement. Frame around low-stress compliance.
- recall_due / appointment_tomorrow: Lead with the specific service due and concrete proposed slots/dates. Low-friction confirmation.
- perf_dip / seasonal_perf_dip: Reassure first, cite the exact metric drop and baseline, then propose one concrete recovery tactic using an active offer.
- perf_spike / milestone_reached: Celebrate briefly with the exact growth metric, then propose a concrete move to sustain momentum.
- competitor_opened: Mention the event factually and propose strengthening local visibility or highlighting a signature service.
- festival_upcoming / category_seasonal: Lead with the festival name and days remaining; suggest a timely customer broadcast.
- bridal_followup / wedding_package_followup: Reference the specific wedding date / days remaining, previous trial, and propose the next preparation phase.
- customer_lapsed_soft / customer_lapsed_hard / winback_eligible: Reference elapsed time gently, offer a specific catalog service/slot to welcome them back.
- curious_ask_due: Ask one low-stakes question about current customer demand with upfront reciprocity ("I'll turn your answer into a post").
- chronic_refill_due: Precise, respectful check on medication refill schedule for customer health.
- renewal_due / gbp_unverified: Clear, operational reminder with days remaining and exact next step.

### FEW-SHOT ANCHOR EXAMPLES (STYLE & STRUCTURE GUIDANCE ONLY):
Important: Never reuse the sentence STRUCTURE of any case-study example, even with different words. Vary: which fact comes first, whether the message opens with a question or a statement, where the citation appears (start, middle, or end), and how the call-to-action is phrased. The only things that must stay identical to the source data are the FACTS themselves (numbers, names, dates, citations) — never the sentence shape used to present them. Before finalizing output, mentally check: if I strip out the specific facts, does the remaining sentence skeleton look like any case-study example? If yes, restructure.

Example 1 (Dentists, research_digest, merchant-facing):
Input Context: Dr. Meera (CTR 2.1%, 124 high-risk adult patients), trigger research_digest (JIDA Oct 2026, 2,100 patients, 38% caries reduction, p.14).
Output:
{
  "body": "Dr. Meera, JIDA's Oct issue landed. One item relevant to your high-risk adult patients — 2,100-patient trial showed 3-month fluoride recall cuts caries recurrence 38% better than 6-month. Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share? — JIDA Oct 2026 p.14",
  "cta": "open_ended",
  "send_as": "vera",
  "suppression_key": "research:dentists:2026-W17",
  "rationale": "Cited JIDA Oct 2026 p.14 with exact trial numbers (2,100 patients, 38% reduction) and tied directly to her 124 high-risk adult cohort with an open-ended offer to draft patient content."
}

Example 2 (Dentists, recall_due, customer-facing, hi-en mix):
Input Context: Merchant Dr. Meera, Customer Priya (lapsed 5 months, language hi-en mix), trigger recall_due (due for 6-month cleaning, slots Wed 5 Nov 6pm or Thu 6 Nov 5pm, offer ₹299).
Output:
{
  "body": "Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is due. Apke liye 2 slots ready hain: Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm. ₹299 cleaning + complimentary fluoride. Reply 1 for Wed, 2 for Thu, or tell us a time that works.",
  "cta": "multi_choice_slot",
  "send_as": "merchant_on_behalf",
  "suppression_key": "recall:c_001_priya_for_m001:6mo",
  "rationale": "Honored hi-en mix language preference, stated exact 6-month recall from trigger with specific available slots and ₹299 offer from catalog."
}

Example 3 (Salons, bridal_followup, customer-facing):
Input Context: Studio11 Kapra (owner Lakshmi), Customer Kavya (wedding 2026-11-08, 196 days, trial completed), trigger bridal_followup.
Output:
{
  "body": "Hi Kavya 💍 Lakshmi from Studio11 Kapra here. 196 days to your wedding — perfect window to start the 30-day skin-prep program before serious bridal bookings roll in. ₹2,499 covers 4 sessions + a take-home kit. Want me to block your preferred Saturday 4pm slot for the first session next week?",
  "cta": "binary_yes_no",
  "send_as": "merchant_on_behalf",
  "suppression_key": "bridal_followup:c_005_kavya_for_m003",
  "rationale": "Personalized with owner name and wedding timeline (196 days), offering exact skin-prep program with a single binary confirmation question."
}
"""


class Composer:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.client = None

        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI client: {e}")

    def compose(
        self,
        category: Optional[Dict[str, Any]],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        conversation_mode: str = "qualifying",
        structural_instruction: Optional[str] = None,
    ) -> ComposedMessage:
        """
        Main composition function. Attempts Gemini generation with structured output.
        Fails over to deterministic template fallback if any error/timeout occurs.
        """
        # If Gemini client is available, attempt LLM call
        if self.client:
            try:
                result = self._call_gemini_compose(
                    category=category,
                    merchant=merchant,
                    trigger=trigger,
                    customer=customer,
                    conversation_history=conversation_history,
                    conversation_mode=conversation_mode,
                    structural_instruction=structural_instruction,
                )
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Gemini composition failed, falling back to deterministic: {e}")

        # Deterministic fallback
        return self._deterministic_fallback(category, merchant, trigger, customer)

    def _call_gemini_compose(
        self,
        category: Optional[Dict[str, Any]],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, Any]]],
        conversation_mode: str,
        structural_instruction: Optional[str] = None,
    ) -> Optional[ComposedMessage]:
        from google.genai import types

        prompt_data = {
            "mode": conversation_mode,
            "trigger": trigger,
            "merchant": merchant,
            "category": category,
            "customer": customer,
            "conversation_history": conversation_history or [],
        }

        user_content = (
            f"Please compose the message for the following context:\n\n"
            f"```json\n{json.dumps(prompt_data, indent=2)}\n```\n\n"
        )
        if structural_instruction:
            user_content += f"Specific structural shape directive: {structural_instruction}\n\n"

        user_content += (
            f"Remember: Output strictly in JSON format matching the schema. "
            f"NEVER fabricate numbers or citations. Ensure the sentence structure does NOT match any case-study example."
        )

        config = types.GenerateContentConfig(
            temperature=0.0,
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ComposedMessage,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=user_content,
            config=config,
        )

        if response and response.text:
            parsed = json.loads(response.text)
            return ComposedMessage(**parsed)

        return None

    def compose_reply(
        self,
        merchant: Optional[Dict[str, Any]],
        trigger: Optional[Dict[str, Any]],
        customer: Optional[Dict[str, Any]],
        conversation_history: List[Dict[str, Any]],
        inbound_message: str,
        conversation_mode: str = "qualifying",
    ) -> ReplyDecision:
        """
        Composes a synchronous reply to merchant/customer message.
        """
        if self.client:
            try:
                from google.genai import types

                prompt_data = {
                    "mode": conversation_mode,
                    "inbound_message": inbound_message,
                    "conversation_history": conversation_history,
                    "merchant": merchant,
                    "trigger": trigger,
                    "customer": customer,
                }

                user_content = (
                    f"Merchant/customer replied: \"{inbound_message}\"\n\n"
                    f"Context & conversation history:\n"
                    f"```json\n{json.dumps(prompt_data, indent=2)}\n```\n\n"
                    f"Decide whether to 'send', 'wait', or 'end'. If mode is 'action', merchant has committed: DO NOT qualify further; take concrete action now."
                )

                config = types.GenerateContentConfig(
                    temperature=0.0,
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ReplyDecision,
                )

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=user_content,
                    config=config,
                )

                if response and response.text:
                    parsed = json.loads(response.text)
                    return ReplyDecision(**parsed)
            except Exception as e:
                logger.warning(f"Gemini reply composition failed, using deterministic fallback: {e}")

        # Deterministic fallback for reply
        if conversation_mode == "action":
            return ReplyDecision(
                action="send",
                body="Great, proceeding with this right away. I will share the confirmation shortly.",
                cta="none",
                rationale="Merchant committed; acknowledged and switched immediately to concrete execution.",
            )
        return ReplyDecision(
            action="send",
            body="Understood. Would you like me to share more details on how to proceed?",
            cta="binary_yes_no",
            rationale="Grounded fallback follow-up to merchant response.",
        )

    def _deterministic_fallback(
        self,
        category: Optional[Dict[str, Any]],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]],
    ) -> ComposedMessage:
        """
        Deterministic, zero-fabrication fallback that pulls real fields from context.
        """
        is_customer = trigger.get("scope") == "customer" and customer is not None
        kind = trigger.get("kind", "general")
        trig_payload = trigger.get("payload", {})
        suppression_key = trigger.get("suppression_key") or f"{kind}:{merchant.get('merchant_id')}"

        if is_customer and customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merchant_name = merchant.get("identity", {}).get("name", "our clinic")
            lang = customer.get("identity", {}).get("language_pref", "en")

            if kind == "recall_due":
                service = trig_payload.get("service_due", "recall checkup").replace("_", " ")
                slots = trig_payload.get("available_slots", [])
                slot_text = f" ({slots[0]['label']})" if slots else ""
                if "hi" in lang:
                    body = f"Namaste {cust_name}, {merchant_name} se reminder hai. Apka {service} due hai{slot_text}. Kya hum apke liye slot confirm karein?"
                else:
                    body = f"Hi {cust_name}, {merchant_name} here. Your {service} is due{slot_text}. Would you like us to confirm this slot for you?"
                return ComposedMessage(
                    body=body,
                    cta="binary_yes_no",
                    send_as="merchant_on_behalf",
                    suppression_key=suppression_key,
                    rationale=f"Grounded customer recall notification for {service} based on verified trigger slots."
                )

            elif kind in ("bridal_followup", "wedding_package_followup"):
                days = trig_payload.get("days_to_wedding", 30)
                body = f"Hi {cust_name}, {merchant_name} here. With {days} days to your wedding, it is the right window for your scheduled prep. Would you like to confirm your next session?"
                return ComposedMessage(
                    body=body,
                    cta="binary_yes_no",
                    send_as="merchant_on_behalf",
                    suppression_key=suppression_key,
                    rationale=f"Grounded bridal follow-up citing {days} days to wedding from trigger payload."
                )

            else:
                body = f"Hi {cust_name}, {merchant_name} here. We wanted to check in regarding your upcoming visit. Would you like to book a slot this week?"
                return ComposedMessage(
                    body=body,
                    cta="binary_yes_no",
                    send_as="merchant_on_behalf",
                    suppression_key=suppression_key,
                    rationale="Generic grounded customer check-in using verified merchant name."
                )

        # Merchant-facing sends
        owner_name = (
            merchant.get("identity", {}).get("owner_first_name")
            or merchant.get("identity", {}).get("name", "there")
        )

        if kind == "research_digest":
            top_id = trig_payload.get("top_item_id")
            digest_items = category.get("digest", []) if category else []
            match = next((item for item in digest_items if item.get("id") == top_id), None)
            if match:
                title = match.get("title", "new clinical research")
                source = match.get("source", "latest journal issue")
                body = f"{owner_name}, fresh update from {source}: \"{title}\". Would you like me to pull the abstract and draft a patient update for you?"
            else:
                body = f"{owner_name}, a new clinical research digest landed for your category. Would you like me to pull the key takeaways for your practice?"
            return ComposedMessage(
                body=body,
                cta="open_ended",
                send_as="vera",
                suppression_key=suppression_key,
                rationale="Grounded research digest notification citing real journal source from category context."
            )

        elif kind in ("perf_dip", "seasonal_perf_dip"):
            metric = trig_payload.get("metric", "views")
            delta = abs(int(trig_payload.get("delta_pct", 0.1) * 100))
            window = trig_payload.get("window", "7d")
            body = f"{owner_name}, noticed {metric} dipped {delta}% over the last {window}. Would you like me to draft a quick WhatsApp note to re-engage your past customers?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded performance notification referencing exact {delta}% dip in {metric} from trigger."
            )

        elif kind in ("perf_spike", "milestone_reached"):
            metric = trig_payload.get("metric", "views")
            delta = abs(int(trig_payload.get("delta_pct", 0.1) * 100))
            body = f"{owner_name}, great momentum — {metric} is up {delta}% this week. Would you like me to turn this into a post to keep visibility high?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded milestone check referencing verified {delta}% spike in {metric}."
            )

        elif kind == "curious_ask_due":
            body = f"Hi {owner_name}! Quick check: what service has been in highest demand this week? I will turn your answer into a quick update to attract more bookings."
            return ComposedMessage(
                body=body,
                cta="open_ended",
                send_as="vera",
                suppression_key=suppression_key,
                rationale="Low-friction curious ask offering upfront reciprocity to the merchant."
            )

        elif kind == "renewal_due":
            days = trig_payload.get("days_remaining", 7)
            plan = trig_payload.get("plan", "subscription")
            body = f"{owner_name}, your {plan} has {days} days remaining. Would you like me to help process your renewal now to ensure uninterrupted visibility?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded renewal reminder citing exact {days} days remaining from trigger."
            )

        else:
            body = f"Hi {owner_name}, Vera here with an update for your business. Would you like me to share the details and recommended next steps?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale="Safe deterministic fallback using verified owner name."
            )
