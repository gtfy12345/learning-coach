from typing import Literal

from pydantic import BaseModel, Field


class Diagnostic(BaseModel):
    """A provider-independent diagnostic question and its teaching metadata."""

    question: str = Field(min_length=1, description="一道不泄露答案的诊断题")
    focus: str = Field(min_length=1, description="这道题主要检查的知识点")
    difficulty: Literal["foundation", "application", "advanced"] = Field(
        description="诊断题难度"
    )


class Assessment(BaseModel):
    """A machine-readable evaluation used by the graph router."""

    score: int = Field(ge=0, le=100, description="回答得分，范围为 0 到 100")
    feedback: str = Field(description="具体、可执行的反馈")
    missing_point: str = Field(description="最主要的知识缺口；没有时写明已经掌握")
