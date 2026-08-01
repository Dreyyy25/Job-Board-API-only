"""Test doubles for AI services.

Stock LangChain fakes raise NotImplementedError on with_structured_output
(BaseChatModel.bind_tools guard), so this project ships its own. Lives
outside tests.py so later phases (resume import, screening) reuse it.
Never imported by production code.
"""
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda


class FakeStructuredChatModel(GenericFakeChatModel):
    """Returns canned parsed output; mirrors include_raw=True shape.

    parsed_outputs is consumed one per call — supply several to script
    retry behaviour. An entry that is an Exception is raised instead
    (simulates provider errors); an entry of None simulates a parse failure.
    """
    parsed_outputs: list[Any] = []
    usage: dict = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    model: str = "fake-model"

    def __init__(self, parsed_outputs=None, **kwargs):
        kwargs.setdefault("messages", iter([]))
        super().__init__(parsed_outputs=list(parsed_outputs or []), **kwargs)

    def with_structured_output(self, schema, method="json_schema", *,
                               include_raw=False, **kwargs):
        def _call(_input):
            item = self.parsed_outputs.pop(0)
            if isinstance(item, Exception):
                raise item
            raw = AIMessage(content="", usage_metadata=dict(self.usage))
            if include_raw:
                error = None if item is not None else ValueError("parse failed")
                return {"raw": raw, "parsed": item, "parsing_error": error}
            return item
        return RunnableLambda(_call)


class ScriptedFakeChatModel(BaseChatModel):
    """Drives a real create_agent loop offline.

    FakeStructuredChatModel cannot: BaseChatModel.bind_tools raises
    NotImplementedError and GenericFakeChatModel does not override it, so an
    agent built on it dies the moment it binds its tools.

    `responses` is consumed one entry per model call. An entry that is an
    Exception is raised instead — script provider failures that way. Entries
    carrying tool_calls drive the agent round the loop.
    """
    responses: list[Any] = []
    model: str = "fake-pro"

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if not self.responses:
            raise AssertionError(
                "ScriptedFakeChatModel ran out of scripted responses — the agent "
                "made more model calls than the test expected.")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])

    def bind_tools(self, tools, **kwargs) -> Runnable:
        # Scripted responses already carry their tool_calls; nothing to bind.
        return self
