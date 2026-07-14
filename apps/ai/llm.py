"""Gemini model factory. The only place LangChain chat models are constructed."""
from langchain_google_genai import ChatGoogleGenerativeAI

from config import AI_MODEL_FLASH, AI_MODEL_PRO, GEMINI_API_KEY

_MODEL_IDS = {'pro': AI_MODEL_PRO, 'flash': AI_MODEL_FLASH}


def get_model(tier: str) -> ChatGoogleGenerativeAI:
    """Return a configured chat model for the given tier ('pro' | 'flash').

    max_retries=0 because the service layer owns the single-retry policy —
    stacking SDK retries on top would multiply latency and cost.
    """
    try:
        model_id = _MODEL_IDS[tier]
    except KeyError:
        raise ValueError(f"Unknown model tier: {tier!r} (expected 'pro' or 'flash')")
    return ChatGoogleGenerativeAI(
        model=model_id,
        api_key=GEMINI_API_KEY,
        timeout=30,
        max_retries=0,
    )
