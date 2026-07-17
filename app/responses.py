"""Fixed response templates.

The escalation messages are deliberately static: no LLM is involved anywhere
in the escalation path, so an API outage or a jailbroken upstream can never
alter what a user in crisis is told.
"""

ESCALATION_EMERGENCY = (
    "🚨 **This may be a medical emergency.**\n\n"
    "Please call **911** (or your local emergency number) right away, or go to the "
    "nearest emergency room. Do not wait to see if symptoms improve.\n\n"
    "If you can, stay with the person, keep them still, and be ready to tell the "
    "dispatcher what happened and what medications are involved.\n\n"
    "I'm a pharmacy information assistant and can't help with emergencies — "
    "emergency services can."
)

ESCALATION_CRISIS = (
    "💙 **You don't have to go through this alone.**\n\n"
    "If you are thinking about harming yourself, please reach out right now:\n\n"
    "- **Call or text 988** — the Suicide & Crisis Lifeline (US), available 24/7\n"
    "- **Text HOME to 741741** — the Crisis Text Line\n"
    "- **Call 911** if you are in immediate danger\n\n"
    "These services are free, confidential, and staffed by people who want to help."
)

ESCALATION_POISON = (
    "🚨 **This may be an overdose or poisoning emergency.**\n\n"
    "- **Call 911** now if the person is unconscious, having trouble breathing, "
    "or having a seizure.\n"
    "- Otherwise call **Poison Control at 1-800-222-1222** (US), available 24/7.\n\n"
    "Have the medication container with you if possible. Do not induce vomiting "
    "unless instructed by Poison Control."
)

BLOCK_INJECTION = (
    "I can't help with that request. I'm a pharmacy information assistant and I "
    "follow strict safety rules that can't be changed by instructions in the chat.\n\n"
    "I'm happy to help with medication questions — side effects, interactions, how "
    "to take an over-the-counter medicine safely, or refill logistics."
)

BLOCK_SCOPE = (
    "I'm not able to help with that — diagnosing conditions and prescribing "
    "medications require a licensed clinician who can examine you and review your "
    "full history.\n\n"
    "Please reach out to your doctor or pharmacist. I'm glad to help with general "
    "medication information: what a drug is for, common side effects, interactions, "
    "and safe use of over-the-counter products."
)

BLOCK_UNSAFE = (
    "I've withheld the assistant's response because it may contain unsafe medical "
    "advice.\n\n"
    "Please talk to your pharmacist or doctor before making any change to how you "
    "take a medication. If this is urgent, call your pharmacy — they can review "
    "your specific situation safely."
)

WARNING_PREFIX = "\n\n---\n**⚠️ Safety notes (added by RxGuard):**\n"

DISCLAIMER = (
    "\n\n*This is general information, not medical advice. Confirm with your "
    "pharmacist or doctor.*"
)
