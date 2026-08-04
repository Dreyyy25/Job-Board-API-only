"""Gemini model factory. The only place LangChain chat models are constructed."""

from langchain_google_genai import ChatGoogleGenerativeAI

from config import AI_MODEL_FLASH, AI_MODEL_PRO, GEMINI_API_KEY

_MODEL_IDS = {'pro': AI_MODEL_PRO, 'flash': AI_MODEL_FLASH}


def get_model(tier: str, *, timeout: int = 30, max_output_tokens: int | None = None) -> ChatGoogleGenerativeAI:
    """Return a configured chat model for the given tier ('pro' | 'flash').

    max_retries=0 because the service layer owns the single-retry policy —
    stacking SDK retries on top would multiply latency and cost.

    timeout defaults to the 30s single-call budget; the chat agent raises it,
    since one turn may involve several sequential model calls.

    max_output_tokens is left unset (provider default) for the structured
    services, whose schemas already bound the output; the chat agent sets it,
    because a free-form completion has no such bound.
    """
    try:
        model_id = _MODEL_IDS[tier]
    except KeyError:
        raise ValueError(f"Unknown model tier: {tier!r} (expected 'pro' or 'flash')")
    return ChatGoogleGenerativeAI(
        model=model_id,
        api_key=GEMINI_API_KEY,
        timeout=timeout,
        max_retries=0,
        max_output_tokens=max_output_tokens,
    )
