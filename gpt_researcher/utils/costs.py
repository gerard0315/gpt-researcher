import tiktoken
from typing import Any

# Per OpenAI Pricing Page: https://openai.com/api/pricing/
ENCODING_MODEL = "o200k_base"
INPUT_COST_PER_TOKEN = 0.000005
OUTPUT_COST_PER_TOKEN = 0.000015
IMAGE_INFERENCE_COST = 0.003825
EMBEDDING_COST = 0.02 / 1000000 # Assumes new ada-3-small


# Cost estimation is via OpenAI libraries and models. May vary for other models
def _to_text(value: Any) -> str:
    """Best-effort conversion to string for token counting.

    The LLM provider may return None or structured objects (dict/list).
    Tokenizers expect a string, so we coerce gracefully instead of raising.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def estimate_llm_cost(input_content: Any, output_content: Any) -> float:
    encoding = tiktoken.get_encoding(ENCODING_MODEL)
    input_tokens = encoding.encode(_to_text(input_content))
    output_tokens = encoding.encode(_to_text(output_content))
    input_costs = len(input_tokens) * INPUT_COST_PER_TOKEN
    output_costs = len(output_tokens) * OUTPUT_COST_PER_TOKEN
    return input_costs + output_costs


def estimate_embedding_cost(model, docs):
    encoding = tiktoken.encoding_for_model(model)
    total_tokens = sum(len(encoding.encode(str(doc))) for doc in docs)
    return total_tokens * EMBEDDING_COST
