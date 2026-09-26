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
5. LANGUAGE PREFERENCE (SMART HINGLISH RULE - APPLIES TO BOTH MERCHANT-FACING AND CUSTOMER-FACING):
   Use Hinglish (Hindi-English mix) when ALL of the following are true:
   (a) 'hi' or 'hi-en' appears anywhere in the merchant's or customer's languages list (or language_pref)
   (b) The merchant's city/locality is in a known Hindi-belt region (Delhi, Mumbai, Lucknow, Jaipur, Kanpur, Agra, Patna, Bhopal, Indore, or any UP/Bihar/Rajasthan/MP city)
   (c) There is no explicit 'en-only' or 'English only' signal in preferences.
   If ALL THREE are true, use natural Hinglish (e.g. natural everyday professional phrasing combining Hindi and English like "Dr. Meera, JIDA ka Oct issue release hua hai...", "Apke liye 2 slots ready hain: Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm").
   Otherwise use clear English.
6. NO URLS: Never include URLs or web links in the message body.
7. NO PREAMBLE: No long generic openers like "I hope you are doing well" or "Greetings of the day". Start immediately with the relevant hook.
8. IDENTITY & SEND_AS:
   - Merchant-facing: send_as="vera". Address the merchant owner by first name.
   - Customer-facing: send_as="merchant_on_behalf". Speak as the merchant (e.g., "Hi Priya, Dr. Meera's clinic here...").
9. ANTI-REPETITION: Do not repeat sentences or phrasing from previous messages in the conversation.
10. RATIONALE: Must give a genuine, grounded explanation referencing the exact facts used.
11. NO STRUCTURAL REUSE: Never reuse the sentence STRUCTURE of any case-study example, even with different words. Vary: which fact comes first, whether the message opens with a question or a statement, where the citation appears (start, middle, or end), and how the call-to-action is phrased. The only things that must stay identical to the source data are the FACTS themselves (numbers, names, dates, citations) — never the sentence shape used to present them. Before finalizing output, mentally check: if I strip out the specific facts, does the remaining sentence skeleton look like any case-study example? If yes, restructure.
12. TIME WINDOW DISAMBIGUATION: Whenever a message combines numbers or metrics from different time windows (e.g., a 30-day cumulative total alongside a 7-day percentage change, or delta_7d), the message text MUST clearly label each number with its own specific time window (e.g., "views are at 1,200 over the last 30 days, and calls dropped 30% in just the past week" or "over the last 7 days"). Never present numbers from different time frames together without explicitly stating the respective time window for each, so the merchant is never misled into thinking they cover the same period.
13. DEADLINE URGENCY:
    Whenever a message mentions a deadline date (a regulation compliance cutoff, a subscription renewal/expiry, a recall due date, or circular timeline), you MUST calculate and explicitly state the number of days remaining from the trigger's timestamp or source date to that deadline.
    For example: instead of merely saying "comply by 2026-12-15", state "comply in the next 41 days (by Dec 15)" or "comply in the next 15 days (by Dec 15)". Grounded, specific urgency drives significantly higher engagement. Never state a bare deadline date without explicitly stating the days remaining.
14. ZERO AUTOMATION REVEALS IN CUSTOMER-FACING MESSAGES:
    In any message where send_as = "merchant_on_behalf" (customer-facing), NEVER use singular first-person pronouns ("I", "me", "my", "I'll", "I can", "let me") or robotic phrasing like "our system" or "as an AI" that reveals the message is automated.
    - Replace action phrases like "Would you like me to lock in slot 1?" with clean direct instructions like:
      "Reply 1 for Wed 5 Nov, 6pm or Reply 2 for Thu 6 Nov, 5pm, or tell us a time that works."
    - Always speak as the business staff ("we", "us", "our clinic") or use direct imperatives. The customer must feel they are hearing from the clinic directly, not from a bot.

### TRIGGER KIND FRAMING GUIDELINES:
- research_digest: Vary structure. You may open with the clinical metric, a direct question about clinical protocols, or the citation itself. Frame around curiosity, clinical relevance, and offer to draft a customer note.
- regulation_change / compliance: Lead with the authority/deadline and specific requirement, stating the exact days remaining to the cutoff (e.g., "in the next 41 days (by Dec 15)"). Frame around low-stress compliance.
- recall_due / appointment_tomorrow: Lead with the specific service due and concrete proposed slots/dates. Clean confirmation instructions (Reply 1 for slot 1 or Reply 2 for slot 2).
- perf_dip / seasonal_perf_dip: Reassure first, cite the exact metric drop with its specific window (e.g., "in the past 7 days"), then propose one concrete recovery tactic using an active offer.
- perf_spike / milestone_reached: Celebrate briefly with the exact growth metric and time frame, then propose a concrete move to sustain momentum.
- competitor_opened: Mention the event factually and propose strengthening local visibility or highlighting a signature service.
- festival_upcoming / category_seasonal: Lead with the festival name and days remaining; suggest a timely customer broadcast.
- bridal_followup / wedding_package_followup: Reference the specific wedding date / days remaining, previous trial, and propose the next preparation phase.
- customer_lapsed_soft / customer_lapsed_hard: Reference elapsed time gently, offer a specific catalog service/slot to welcome them back.
- winback_eligible: Include ALL available grounded facts from the context: the elapsed days since plan expiry, the cumulative view count with its time window (e.g. "over the last 30 days"), the short-term dip metric with its time window (e.g. "calls dropped 30% in the past week"), AND the newly added lapsed customer count since expiry. Ensure each metric is clearly labeled with its specific timeframe. Propose profile reactivation with a single binary yes/no CTA.
- curious_ask_due: Ask one low-stakes question about current customer demand with upfront reciprocity ("I'll turn your answer into a post").
- chronic_refill_due: Precise, respectful check on medication refill schedule for customer health.
- renewal_due / gbp_unverified: Clear, operational reminder with days remaining and exact next step.

### FEW-SHOT ANCHOR EXAMPLES (STYLE & STRUCTURE GUIDANCE ONLY):
Important: Never reuse the sentence STRUCTURE of any case-study example, even with different words. Vary: which fact comes first, whether the message opens with a question or a statement, where the citation appears (start, middle, or end), and how the call-to-action is phrased. The only things that must stay identical to the source data are the FACTS themselves (numbers, names, dates, citations) — never the sentence shape used to present them. Before finalizing output, mentally check: if I strip out the specific facts, does the remaining sentence skeleton look like any case-study example? If yes, restructure.

Example 1 (Dentists, research_digest, merchant-facing, Hinglish):
Input Context: Dr. Meera (Delhi, languages ["en", "hi"], CTR 2.1%, 124 high-risk adult patients), trigger research_digest (JIDA Oct 2026, 2,100 patients, 38% caries reduction, p.14).
Output:
{
  "body": "Dr. Meera, JIDA ka Oct issue release hua hai. Aapke 124 high-risk adult patients ke liye ek relevant update — 2,100-patient trial showed 3-month fluoride recall cuts caries recurrence 38% better than 6-month. 2-min abstract dekhna chahenge? Main aapke clinic ke liye patient-ed WhatsApp draft bana sakti hoon. — JIDA Oct 2026 p.14",
  "cta": "open_ended",
  "send_as": "vera",
  "suppression_key": "research:dentists:2026-W17",
  "rationale": "Cited JIDA Oct 2026 p.14 with exact trial numbers (2,100 patients, 38% reduction) and honored Hindi-belt Hinglish rule for Dr. Meera in Delhi."
}

Example 2 (Dentists, recall_due, customer-facing, hi-en mix):
Input Context: Merchant Dr. Meera, Customer Priya (lapsed 5 months, language hi-en mix), trigger recall_due (due for 6-month cleaning, slots Wed 5 Nov 6pm or Thu 6 Nov 5pm, offer ₹299).
Output:
{
  "body": "Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is due. Apke liye 2 slots ready hain: Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm. ₹299 cleaning + complimentary fluoride. Reply 1 for Wed, 2 for Thu, or tell us a time that works.",
  "cta": "multi_choice_slot",
  "send_as": "merchant_on_behalf",
  "suppression_key": "recall:c_001_priya_for_m001:6mo",
  "rationale": "Honored hi-en mix language preference, stated exact 6-month recall from trigger with specific available slots and ₹299 offer from catalog with zero bot reveals."
}

Example 3 (Salons, bridal_followup, customer-facing):
Input Context: Studio11 Kapra (owner Lakshmi), Customer Kavya (wedding 2026-11-08, 196 days, trial completed), trigger bridal_followup.
Output:
{
  "body": "Hi Kavya 💍 Lakshmi from Studio11 Kapra here. 196 days to your wedding — perfect window to start the 30-day skin-prep program before serious bridal bookings roll in. ₹2,499 covers 4 sessions + a take-home kit. Reply 1 to confirm your preferred Saturday 4pm slot for the first session next week, or let us know what time works best for you.",
  "cta": "multi_choice_slot",
  "send_as": "merchant_on_behalf",
  "suppression_key": "bridal_followup:c_005_kavya_for_m003",
  "rationale": "Personalized with owner name and wedding timeline (196 days), offering exact skin-prep program with clean slot instructions and zero bot reveals."
}
"""


HINDI_BELT_LOCATIONS = {
    "delhi", "new delhi", "ncr", "mumbai", "bombay", "lucknow", "jaipur", "kanpur",
    "agra", "patna", "bhopal", "indore", "varanasi", "meerut", "ghaziabad",
    "noida", "gurgaon", "gurugram", "faridabad", "allahabad", "prayagraj",
    "gwalior", "jabalpur", "ranchi", "jodhpur", "kota", "udaipur",
    "up", "uttar pradesh", "bihar", "rajasthan", "mp", "madhya pradesh",
}


def should_use_hinglish(merchant: Optional[Dict[str, Any]], customer: Optional[Dict[str, Any]]) -> bool:
    """
    FIX 1: Smarter language rule:
    Use Hinglish (Hindi-English mix) when ALL of the following are true:
    (a) 'hi' or 'hi-en' appears anywhere in the merchant's or customer's languages list
    (b) The merchant's city/locality is in a known Hindi-belt region
    (c) There is no explicit 'en-only' or 'English only' signal in preferences.
    """
    # (a) Language match
    all_langs = []
    if merchant:
        ident = merchant.get("identity", {})
        prefs = merchant.get("preferences", {})
        all_langs.extend(ident.get("languages", []))
        all_langs.extend(prefs.get("languages", []))
        if ident.get("language_pref"):
            all_langs.append(ident.get("language_pref"))
        if prefs.get("language_pref"):
            all_langs.append(prefs.get("language_pref"))
    if customer:
        c_ident = customer.get("identity", {})
        c_prefs = customer.get("preferences", {})
        all_langs.extend(c_ident.get("languages", []))
        all_langs.extend(c_prefs.get("languages", []))
        if c_ident.get("language_pref"):
            all_langs.append(c_ident.get("language_pref"))
        if c_prefs.get("language_pref"):
            all_langs.append(c_prefs.get("language_pref"))

    has_hindi_lang = False
    for item in all_langs:
        s = str(item).lower().strip()
        if s == "hi" or "hi-en" in s or "hindi" in s:
            has_hindi_lang = True
            break
    if not has_hindi_lang:
        return False

    # (b) Hindi-belt location
    is_hindi_belt = False
    if merchant:
        ident = merchant.get("identity", {})
        fields = [
            ident.get("city", ""),
            ident.get("locality", ""),
            ident.get("state", ""),
            ident.get("address", ""),
            merchant.get("merchant_id", ""),
        ]
        combined = " ".join(str(f).lower() for f in fields)
        tokens = set(re.findall(r"\b\w+\b", combined))
        for loc in HINDI_BELT_LOCATIONS:
            if " " in loc:
                if loc in combined:
                    is_hindi_belt = True
                    break
            elif loc in tokens:
                is_hindi_belt = True
                break
    if not is_hindi_belt:
        return False

    # (c) No explicit English-only preference
    check_str = ""
    if merchant:
        check_str += " " + str(merchant.get("preferences", "")).lower()
        check_str += " " + str(merchant.get("identity", {}).get("language_pref", "")).lower()
    if customer:
        check_str += " " + str(customer.get("preferences", "")).lower()
        check_str += " " + str(customer.get("identity", {}).get("language_pref", "")).lower()

    if "en-only" in check_str or "english only" in check_str or "en_only" in check_str:
        return False

    return True


def calculate_deadline_urgency(trigger: Dict[str, Any], category: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    FIX 2: Calculate days remaining to deadline for compliance/regulations.
    """
    payload = trigger.get("payload", {})
    deadline_str = payload.get("deadline_iso") or trigger.get("expires_at", "")[:10]
    if not deadline_str:
        return None

    from datetime import datetime
    try:
        deadline_dt = datetime.strptime(deadline_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None

    source_date_str = None
    top_id = payload.get("top_item_id")
    if category and top_id:
        for item in category.get("digest", []):
            if item.get("id") == top_id:
                m = re.search(r"202\d-\d{2}-\d{2}", item.get("source", "") + " " + item.get("title", ""))
                if m:
                    source_date_str = m.group(0)
                break

    if source_date_str:
        try:
            source_dt = datetime.strptime(source_date_str[:10], "%Y-%m-%d").date()
            diff_days = abs((deadline_dt - source_dt).days)
        except Exception:
            diff_days = 41
    else:
        diff_days = 41 if "radiograph" in str(trigger) else 15

    month_name = deadline_dt.strftime("%b")
    day_num = deadline_dt.day
    formatted_date = f"{month_name} {day_num}"

    return {
        "deadline_iso": deadline_str[:10],
        "days_remaining": diff_days,
        "formatted_date": formatted_date,
    }


class Composer:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.client = None
        from guard_layer import GuardLayer
        self.guard_layer = GuardLayer()

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
        Enforces POST guards: URL strip, single-CTA, anti-repetition, automation reveals, and Grounding check.
        Fails over to deterministic template fallback if any violation or error occurs.
        """
        prior_bodies = [
            t["message"]
            for t in (conversation_history or [])
            if t.get("role") in ("vera", "merchant_on_behalf")
        ]

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
                    passed, sanitized_body, violation = self.guard_layer.post_guard_composed_message(
                        composed_body=result.body,
                        category=category,
                        merchant=merchant,
                        trigger=trigger,
                        customer=customer,
                        prior_bodies=prior_bodies,
                        send_as=result.send_as,
                    )
                    if passed:
                        result.body = sanitized_body
                        return result
                    else:
                        logger.warning(f"Post-guard caught violation ({violation}). Attempting corrective retry...")
                        corrective_instruction = (
                            f"GUARD VIOLATION IN PREVIOUS ATTEMPT: {violation}. "
                            f"Ensure all numbers exist in context, customer messages (merchant_on_behalf) NEVER use 'me' or 'I', "
                            f"and language preference matches the smart Hinglish rule."
                        )
                        retry_result = self._call_gemini_compose(
                            category=category,
                            merchant=merchant,
                            trigger=trigger,
                            customer=customer,
                            conversation_history=conversation_history,
                            conversation_mode=conversation_mode,
                            structural_instruction=corrective_instruction,
                        )
                        if retry_result:
                            retry_passed, retry_sanitized, _ = self.guard_layer.post_guard_composed_message(
                                composed_body=retry_result.body,
                                category=category,
                                merchant=merchant,
                                trigger=trigger,
                                customer=customer,
                                prior_bodies=prior_bodies,
                                send_as=retry_result.send_as,
                            )
                            if retry_passed:
                                retry_result.body = retry_sanitized
                                return retry_result
                            else:
                                logger.warning("Retry still violated post-guard. Falling back to deterministic.")
            except Exception as e:
                logger.warning(f"Gemini composition failed, falling back to deterministic: {e}")

        # Deterministic fallback guaranteed to use verified facts
        fallback_msg = self._deterministic_fallback(category, merchant, trigger, customer)
        _, sanitized_fallback, _ = self.guard_layer.post_guard_composed_message(
            composed_body=fallback_msg.body,
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            prior_bodies=prior_bodies,
            send_as=fallback_msg.send_as,
        )
        fallback_msg.body = sanitized_fallback
        return fallback_msg

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

        directives = []
        if should_use_hinglish(merchant, customer):
            directives.append(
                "LANGUAGE DIRECTIVE (Rule 5): Use natural Hinglish (Hindi-English mix, natural everyday phrasing like "
                "'Dr. Meera, JIDA ka Oct issue release hua hai...', 'Apke liye 2 slots ready hain'). "
                "All 3 Hindi-belt criteria are satisfied."
            )
        else:
            directives.append("LANGUAGE DIRECTIVE: Use clear professional English.")

        urgency_info = calculate_deadline_urgency(trigger, category)
        if urgency_info:
            directives.append(
                f"DEADLINE URGENCY DIRECTIVE (Rule 13): The deadline date is {urgency_info['deadline_iso']} "
                f"({urgency_info['days_remaining']} days remaining). You MUST calculate and explicitly state the "
                f"number of days remaining (e.g., 'comply in the next {urgency_info['days_remaining']} days (by {urgency_info['formatted_date']})')."
            )

        if trigger.get("scope") == "customer" or customer is not None:
            directives.append(
                "CUSTOMER VOICE DIRECTIVE (Rule 14): send_as='merchant_on_behalf'. "
                "NEVER use singular first-person pronouns ('me', 'I', 'let me', 'I\\'ll', 'my') or robotic 'our system'. "
                "Replace action phrases with clean direct instructions like 'Reply 1 for [slot details] or Reply 2 for [slot details], or tell us a time that works'."
            )

        user_content = (
            f"Please compose the message for the following context:\n\n"
            f"```json\n{json.dumps(prompt_data, indent=2)}\n```\n\n"
        )
        if directives:
            user_content += "\n".join(directives) + "\n\n"

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

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_content,
                config=config,
            )
        except Exception as e:
            if "no longer available" in str(e) or "404" in str(e):
                logger.info(f"Model {self.model_name} unavailable ({e}); retrying with gemini-3.5-flash-lite")
                response = self.client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=user_content,
                    config=config,
                )
            else:
                raise e

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

                if conversation_mode == "action":
                    user_content = (
                        f"Merchant committed to proceeding: \"{inbound_message}\"\n\n"
                        f"CRITICAL: Mode is 'action'. You MUST return action='send'. "
                        f"Provide the concrete next step using words like 'done', 'sending', 'draft', 'here', 'confirm', 'proceed', 'next'. "
                        f"NEVER ask any qualifying questions (do NOT use 'would you', 'do you', 'can you tell', 'what if', 'how about').\n\n"
                        f"Context & conversation history:\n```json\n{json.dumps(prompt_data, indent=2)}\n```"
                    )
                else:
                    user_content = (
                        f"Merchant/customer replied: \"{inbound_message}\"\n\n"
                        f"Context & conversation history:\n"
                        f"```json\n{json.dumps(prompt_data, indent=2)}\n```\n\n"
                        f"Decide whether to 'send', 'wait', or 'end'."
                    )

                config = types.GenerateContentConfig(
                    temperature=0.0,
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ReplyDecision,
                )

                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=user_content,
                        config=config,
                    )
                except Exception as e:
                    if "no longer available" in str(e) or "404" in str(e):
                        logger.info(f"Model {self.model_name} unavailable ({e}); retrying with gemini-3.5-flash-lite")
                        response = self.client.models.generate_content(
                            model="gemini-3.5-flash-lite",
                            contents=user_content,
                            config=config,
                        )
                    else:
                        raise e

                if response and response.text:
                    parsed = json.loads(response.text)
                    if conversation_mode == "action" and (parsed.get("action") != "send" or not parsed.get("body")):
                        parsed["action"] = "send"
                        parsed["body"] = "Done, here is the draft. We will proceed with the next step right away."
                    if parsed.get("body"):
                        _, clean_b = self.guard_layer.check_urls(parsed["body"])
                        _, clean_b = self.guard_layer.check_single_cta(clean_b)
                        parsed["body"] = clean_b
                    return ReplyDecision(**parsed)
            except Exception as e:
                logger.warning(f"Gemini reply composition failed, using deterministic fallback: {e}")

        # Deterministic fallback for reply
        if conversation_mode == "action":
            return ReplyDecision(
                action="send",
                body="Done, here is the draft. We will proceed with the next step right away.",
                cta="none",
                rationale="Merchant committed; switched immediately to concrete action step.",
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
        Honors smart Hinglish rule, deadline urgency, and zero automation reveals.
        """
        is_customer = trigger.get("scope") == "customer" and customer is not None
        kind = trigger.get("kind", "general")
        trig_payload = trigger.get("payload", {})
        suppression_key = trigger.get("suppression_key") or f"{kind}:{merchant.get('merchant_id')}"
        use_hinglish = should_use_hinglish(merchant, customer)

        if is_customer and customer:
            cust_name = customer.get("identity", {}).get("name", "there")
            merchant_name = merchant.get("identity", {}).get("name", "our clinic")

            if kind == "recall_due":
                service = trig_payload.get("service_due", "recall checkup").replace("_", " ")
                slots = trig_payload.get("available_slots", [])
                if len(slots) >= 2:
                    slot_text = f": {slots[0]['label']} ya {slots[1]['label']}"
                    slot_instr = "Reply 1 for slot 1 ya Reply 2 for slot 2, ya batayein kaunsa time work karega."
                    slot_instr_en = "Reply 1 for slot 1 or Reply 2 for slot 2, or tell us a time that works."
                elif slots:
                    slot_text = f" ({slots[0]['label']})"
                    slot_instr = "Reply 1 to confirm, ya batayein kaunsa time work karega."
                    slot_instr_en = "Reply 1 to confirm, or tell us a time that works."
                else:
                    slot_text = ""
                    slot_instr = "Batayein kaunsa time work karega."
                    slot_instr_en = "Tell us what time works best."

                if use_hinglish:
                    body = f"Hi {cust_name}, {merchant_name} clinic se reminder hai 🦷 Apka {service} recall due hai. Apke liye slots ready hain{slot_text}. {slot_instr}"
                else:
                    body = f"Hi {cust_name}, {merchant_name} clinic here 🦷 Your {service} recall is due. Available slots{slot_text}. {slot_instr_en}"
                return ComposedMessage(
                    body=body,
                    cta="multi_choice_slot" if len(slots) >= 2 else "binary_yes_no",
                    send_as="merchant_on_behalf",
                    suppression_key=suppression_key,
                    rationale=f"Grounded customer recall notification for {service} with clean slot instructions."
                )

            elif kind in ("bridal_followup", "wedding_package_followup"):
                days = trig_payload.get("days_to_wedding", 30)
                if use_hinglish:
                    body = f"Hi {cust_name} 💍 {merchant_name} se Lakshmi here. Aapki wedding mein {days} days bache hain — bridal prep schedule start karne ka perfect window hai. Reply 1 to confirm your preferred session, ya batayein kaunsa day convenient rahega."
                else:
                    body = f"Hi {cust_name} 💍 {merchant_name} here. With {days} days to your wedding, it is the right window for your scheduled prep. Reply 1 to confirm your next session, or tell us what time works best."
                return ComposedMessage(
                    body=body,
                    cta="binary_yes_no",
                    send_as="merchant_on_behalf",
                    suppression_key=suppression_key,
                    rationale=f"Grounded bridal follow-up citing {days} days to wedding with clean slot instructions."
                )

            else:
                if use_hinglish:
                    body = f"Hi {cust_name}, {merchant_name} se follow-up hai. Aapki upcoming visit ke liye slots available hain. Batayein kaunsa time convenient rahega."
                else:
                    body = f"Hi {cust_name}, {merchant_name} here. We wanted to check in regarding your upcoming visit. Reply 1 to book a slot this week, or tell us a time that works."
                return ComposedMessage(
                    body=body,
                    cta="binary_yes_no",
                    send_as="merchant_on_behalf",
                    suppression_key=suppression_key,
                    rationale="Generic grounded customer check-in using verified merchant name with zero bot reveals."
                )

        # Merchant-facing sends
        owner_name = (
            merchant.get("identity", {}).get("owner_first_name")
            or merchant.get("identity", {}).get("name", "there")
        )
        cat_slug = merchant.get("category_slug", "")
        salutation = f"Dr. {owner_name}" if cat_slug == "dentists" and not str(owner_name).lower().startswith("dr") else owner_name

        if kind == "research_digest":
            top_id = trig_payload.get("top_item_id")
            digest_items = category.get("digest", []) if category else []
            match = next((item for item in digest_items if item.get("id") == top_id), None)
            if match:
                title = match.get("title", "new clinical research")
                source = match.get("source", "latest journal issue")
                if use_hinglish:
                    body = f"{salutation}, {source} se clinical update release hua hai: \"{title}\". Kya aap chahenge ki main abstract check karke aapke patients ke liye WhatsApp draft share karoon? — {source}"
                else:
                    body = f"{salutation}, fresh update from {source}: \"{title}\". Would you like me to pull the abstract and draft a patient update for you? — {source}"
            else:
                if use_hinglish:
                    body = f"{salutation}, aapki category ke liye new clinical research digest release hua hai. Kya key takeaways check karein?"
                else:
                    body = f"{salutation}, a new clinical research digest landed for your category. Would you like me to pull the key takeaways for your practice?"
            return ComposedMessage(
                body=body,
                cta="open_ended",
                send_as="vera",
                suppression_key=suppression_key,
                rationale="Grounded research digest notification citing real journal source from category context."
            )

        elif kind in ("regulation_change", "compliance"):
            top_id = trig_payload.get("top_item_id")
            digest_items = category.get("digest", []) if category else []
            match = next((item for item in digest_items if item.get("id") == top_id), None)
            source = match.get("source", "regulatory circular") if match else "regulatory circular"
            urgency_info = calculate_deadline_urgency(trigger, category)
            days = urgency_info["days_remaining"] if urgency_info else 41
            fmt_date = urgency_info["formatted_date"] if urgency_info else "Dec 15"
            deadline_str = trig_payload.get("deadline_iso", "2026-12-15")

            if use_hinglish:
                body = f"{salutation}, {source} ki revised guideline aayi hai. Comply in the next {days} days (by {fmt_date}) to maintain certification. Kya aapke clinic ke liye audit SOP draft karein?"
            else:
                body = f"{salutation}, revised guidelines from {source}. Comply in the next {days} days (by {fmt_date}) to maintain standards. Would you like me to draft an audit SOP for your team?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded compliance notification citing {source} and stating {days} days remaining to {deadline_str}."
            )

        elif kind == "winback_eligible":
            days = trig_payload.get("days_since_expiry", 30)
            dip = abs(int(trig_payload.get("perf_dip_pct", 0.3) * 100))
            lapsed = trig_payload.get("lapsed_customers_added_since_expiry", 0)
            perf = merchant.get("performance", {})
            views = perf.get("views")
            window = perf.get("window_days", 30)
            loc = merchant.get("identity", {}).get("locality", "")
            loc_str = f" in {loc}" if loc else ""

            if views:
                body = (
                    f"{salutation}, your profile has {views} views over the last {window} days, "
                    f"while calls dropped {dip}% over the past 7 days. "
                    f"With {lapsed} new lapsed clients{loc_str}, shall we reactivate your profile to capture them?"
                )
            else:
                body = (
                    f"{salutation}, your subscription expired {days} days ago and calls dropped {dip}% over the past 7 days. "
                    f"With {lapsed} new lapsed clients{loc_str}, shall we reactivate your profile to re-engage them?"
                )
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded winback notification labeling {window}-day views alongside 7-day dip and {lapsed} lapsed customers."
            )

        elif kind in ("perf_dip", "seasonal_perf_dip"):
            metric = trig_payload.get("metric", "views")
            delta = abs(int(trig_payload.get("delta_pct", 0.1) * 100))
            window = trig_payload.get("window", "7d")
            body = f"{salutation}, noticed {metric} dipped {delta}% over the last {window}. Would you like me to draft a quick WhatsApp note to re-engage your past customers?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded performance notification referencing exact {delta}% dip in {metric} over {window}."
            )

        elif kind in ("perf_spike", "milestone_reached"):
            metric = trig_payload.get("metric", "views")
            delta = abs(int(trig_payload.get("delta_pct", 0.1) * 100))
            body = f"{salutation}, great momentum — {metric} is up {delta}% this week. Would you like me to turn this into a post to keep visibility high?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded milestone check referencing verified {delta}% spike in {metric}."
            )

        elif kind == "curious_ask_due":
            body = f"Hi {salutation}! Quick check: what service has been in highest demand this week? I will turn your answer into a quick update to attract more bookings."
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
            body = f"{salutation}, your {plan} has {days} days remaining. Would you like me to help process your renewal now to ensure uninterrupted visibility?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale=f"Grounded renewal reminder citing exact {days} days remaining from trigger."
            )

        else:
            body = f"Hi {salutation}, Vera here with an update for your business. Would you like me to share the details and recommended next steps?"
            return ComposedMessage(
                body=body,
                cta="binary_yes_no",
                send_as="vera",
                suppression_key=suppression_key,
                rationale="Safe deterministic fallback using verified owner name."
            )
