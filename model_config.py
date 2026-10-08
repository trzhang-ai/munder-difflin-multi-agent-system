import os
from dotenv import load_dotenv
from smolagents import OpenAIServerModel


def create_model() -> OpenAIServerModel:
    """Chat model shared by every agent; credentials come from .env."""
    load_dotenv()

    return OpenAIServerModel(
        model_id=os.getenv("OPENAI_MODEL") or "gpt-5.6-luna",
        api_base=os.getenv("OPENAI_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        reasoning_effort="none",
    )
