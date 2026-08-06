import os
from typing import Any

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model


def create_chat_model() -> Any:
    """Create the chat model configured by MODEL_ID in the local environment."""

    load_dotenv()
    model_id = os.getenv("MODEL_ID", "").strip()
    if not model_id:
        raise RuntimeError(
            "没有找到 MODEL_ID。请复制 .env.example 为 .env，并填写可用模型。"
        )

    return init_chat_model(model_id, temperature=0)
