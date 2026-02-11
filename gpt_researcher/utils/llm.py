# libraries
from __future__ import annotations

import logging
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from gpt_researcher.llm_provider.generic.base import NO_SUPPORT_TEMPERATURE_MODELS, SUPPORT_REASONING_EFFORT_MODELS, ReasoningEfforts

from ..prompts import PromptFamily
from .costs import estimate_llm_cost
from .validators import Subtopics
import os
import copy


def get_llm(llm_provider, **kwargs):
    from gpt_researcher.llm_provider import GenericLLMProvider
    return GenericLLMProvider.from_provider(llm_provider, **kwargs)


def _split_llm_kwargs(llm_kwargs: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Extract provider-auth metadata from llm_kwargs."""
    if not llm_kwargs:
        return {}, {}
    kwargs_copy = dict(llm_kwargs)
    provider_auth = kwargs_copy.pop("__provider_auth__", {})
    if not isinstance(provider_auth, dict):
        provider_auth = {}
    return kwargs_copy, provider_auth


def _apply_provider_auth(
    provider_kwargs: dict[str, Any],
    llm_provider: str | None,
    provider_auth: dict[str, dict[str, Any]],
) -> None:
    """Merge per-provider auth info into provider kwargs."""
    if not llm_provider:
        return
    auth_config = provider_auth.get(llm_provider)
    if not isinstance(auth_config, dict):
        return
    for key, value in auth_config.items():
        if value is not None:
            provider_kwargs[key] = value


def _build_kimi_provider_kwargs(
    base_kwargs: dict[str, Any],
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    """Prepare kwargs for Kimi (Moonshot) fallback while preserving caller options."""
    fallback_model = os.getenv("KIMI_FALLBACK_MODEL", "moonshot:kimi-k2-turbo-preview")
    kwargs = copy.deepcopy(base_kwargs)
    kwargs["model"] = fallback_model
    kwargs["openai_api_key"] = os.environ.get("KIMI_API_KEY")
    kwargs["openai_api_base"] = "https://api.moonshot.cn/v1"

    if fallback_model not in NO_SUPPORT_TEMPERATURE_MODELS:
        kwargs["temperature"] = temperature
        kwargs["max_tokens"] = max_tokens
    else:
        kwargs["temperature"] = None
        kwargs["max_tokens"] = None

    return kwargs


async def create_chat_completion(
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = 0.4,
        max_tokens: int | None = 4000,
        llm_provider: str | None = None,
        stream: bool = False,
        websocket: Any | None = None,
        llm_kwargs: dict[str, Any] | None = None,
        cost_callback: callable = None,
        reasoning_effort: str | None = ReasoningEfforts.Medium.value,
        **kwargs
) -> str:
    """Create a chat completion using the OpenAI API
    Args:
        messages (list[dict[str, str]]): The messages to send to the chat completion.
        model (str, optional): The model to use. Defaults to None.
        temperature (float, optional): The temperature to use. Defaults to 0.4.
        max_tokens (int, optional): The max tokens to use. Defaults to 4000.
        llm_provider (str, optional): The LLM Provider to use.
        stream (bool): Whether to stream the response. Defaults to False.
        webocket (WebSocket): The websocket used in the currect request,
        llm_kwargs (dict[str, Any], optional): Additional LLM keyword arguments. Defaults to None.
        cost_callback: Callback function for updating cost.
        reasoning_effort (str, optional): Reasoning effort for OpenAI's reasoning models. Defaults to 'low'.
        **kwargs: Additional keyword arguments.
    Returns:
        str: The response from the chat completion.
    """
    # validate input
    if model is None:
        raise ValueError("Model cannot be None")
    if max_tokens is not None and max_tokens > 32001:
        raise ValueError(
            f"Max tokens cannot be more than 32,000, but got {max_tokens}")

    # Get the provider from supported providers
    provider_kwargs = {'model': model}

    extracted_llm_kwargs, provider_auth = _split_llm_kwargs(llm_kwargs)
    if extracted_llm_kwargs:
        provider_kwargs.update(extracted_llm_kwargs)
    _apply_provider_auth(provider_kwargs, llm_provider, provider_auth)

    # Optional: enable OpenAI input caching via env flag
    if llm_provider == "openai" and os.getenv("OPENAI_INPUT_CACHE", "").lower() in {"1", "true", "yes", "on"}:
        beta_header = "input-caching"
        extra_headers = provider_kwargs.get("extra_headers", {})
        # Preserve any existing OpenAI-Beta header by appending when appropriate
        if "OpenAI-Beta" in extra_headers and beta_header not in extra_headers["OpenAI-Beta"]:
            extra_headers["OpenAI-Beta"] = f"{extra_headers['OpenAI-Beta']}, {beta_header}"
        else:
            extra_headers["OpenAI-Beta"] = beta_header
        provider_kwargs["extra_headers"] = extra_headers

    if model in SUPPORT_REASONING_EFFORT_MODELS:
        provider_kwargs['reasoning_effort'] = reasoning_effort

    if model not in NO_SUPPORT_TEMPERATURE_MODELS:
        provider_kwargs['temperature'] = temperature
        provider_kwargs['max_tokens'] = max_tokens
    else:
        provider_kwargs['temperature'] = None
        provider_kwargs['max_tokens'] = None

    if llm_provider == "openai":
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url and "openai_api_base" not in provider_kwargs:
            provider_kwargs['openai_api_base'] = base_url

    provider = get_llm(llm_provider, **provider_kwargs)
    response = ""
    last_error = None
    # create response
    for attempt in range(3):  # maximum of 3 attempts
        try:
            response = await provider.get_chat_response(
                messages, stream, websocket, **kwargs
            )

            if cost_callback:
                llm_costs = estimate_llm_cost(str(messages), response)
                cost_callback(llm_costs)

            return response
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            # Only retry on transient/connection errors
            is_transient = any(s in error_str for s in [
                "connection", "timeout", "server disconnected",
                "remote protocol error", "temporarily unavailable",
                "502", "503", "504",
            ])
            if is_transient and attempt < 2:
                wait = 2 ** attempt  # 1s, 2s
                logging.warning(f"Transient error from {llm_provider} (attempt {attempt + 1}/3): {e}. Retrying in {wait}s...")
                import asyncio
                await asyncio.sleep(wait)
                continue
            raise

    # Fallback to Kimi/Moonshot if configured and primary provider failed
    kimi_key = os.environ.get("KIMI_API_KEY")
    if llm_provider != "moonshot" and kimi_key:
        logging.warning(f"{llm_provider} failed after retries; falling back to Kimi.")
        kimi_kwargs = _build_kimi_provider_kwargs(provider_kwargs, temperature, max_tokens)
        try:
            kimi_provider = get_llm("moonshot", **kimi_kwargs)
            response = await kimi_provider.get_chat_response(
                messages, stream, websocket, **kwargs
            )
            if cost_callback:
                llm_costs = estimate_llm_cost(str(messages), response)
                cost_callback(llm_costs)
            return response
        except Exception as kimi_exc:
            last_error = kimi_exc

    logging.error(f"Failed to get response from {llm_provider} API after 3 attempts")
    raise RuntimeError(f"Failed to get response from {llm_provider} API: {last_error}")


async def construct_subtopics(
    task: str,
    data: str,
    config,
    subtopics: list = [],
    prompt_family: type[PromptFamily] | PromptFamily = PromptFamily,
    **kwargs
) -> list:
    """
    Construct subtopics based on the given task and data.

    Args:
        task (str): The main task or topic.
        data (str): Additional data for context.
        config: Configuration settings.
        subtopics (list, optional): Existing subtopics. Defaults to [].
        prompt_family (PromptFamily): Family of prompts
        **kwargs: Additional keyword arguments.

    Returns:
        list: A list of constructed subtopics.
    """
    try:
        parser = PydanticOutputParser(pydantic_object=Subtopics)

        prompt = PromptTemplate(
            template=prompt_family.generate_subtopics_prompt(),
            input_variables=["task", "data", "subtopics", "max_subtopics"],
            partial_variables={
                "format_instructions": parser.get_format_instructions()},
        )

        provider_kwargs = {'model': config.smart_llm_model}
        extracted_llm_kwargs, provider_auth = _split_llm_kwargs(config.llm_kwargs)
        if extracted_llm_kwargs:
            provider_kwargs.update(extracted_llm_kwargs)
        _apply_provider_auth(provider_kwargs, config.smart_llm_provider, provider_auth)

        if config.smart_llm_model in SUPPORT_REASONING_EFFORT_MODELS:
            provider_kwargs['reasoning_effort'] = ReasoningEfforts.High.value
        else:
            provider_kwargs['temperature'] = config.temperature
            provider_kwargs['max_tokens'] = config.smart_token_limit

        provider = get_llm(config.smart_llm_provider, **provider_kwargs)

        model = provider.llm

        chain = prompt | model | parser

        try:
            output = await chain.ainvoke({
                "task": task,
                "data": data,
                "subtopics": subtopics,
                "max_subtopics": config.max_subtopics
            }, **kwargs)
        except Exception:
            kimi_key = os.environ.get("KIMI_API_KEY")
            if config.smart_llm_provider != "moonshot" and kimi_key:
                kimi_kwargs = _build_kimi_provider_kwargs(provider_kwargs, config.temperature, config.smart_token_limit)
                kimi_provider = get_llm("moonshot", **kimi_kwargs)
                chain = prompt | kimi_provider.llm | parser
                output = await chain.ainvoke({
                    "task": task,
                    "data": data,
                    "subtopics": subtopics,
                    "max_subtopics": config.max_subtopics
                }, **kwargs)
            else:
                raise

        return output

    except Exception as e:
        print("Exception in parsing subtopics : ", e)
        logging.getLogger(__name__).error("Exception in parsing subtopics : \n {e}")
        return subtopics
