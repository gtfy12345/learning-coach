from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from learning_coach.model import LearningCoachModels
from learning_coach.schemas import Assessment, Diagnostic

TaskInput = dict[str, Any]


DIAGNOSTIC_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "你是技术学习教练。只出一道诊断题，不要给答案。"),
        MessagesPlaceholder("diagnostic_messages"),
    ]
)

TEACHING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是技术学习教练。针对薄弱点讲解，并使用一个具体代码场景。",
        ),
        (
            "user",
            """主题：{topic}
诊断重点：{diagnostic_focus}
诊断难度：{diagnostic_difficulty}
诊断回答：{diagnostic_answer}
上次反馈：{feedback}
尚未掌握：{missing_point}
请控制在 300 字内，不要只重复定义。""",
        ),
    ]
)

QUIZ_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "只出一道新的应用题，不要泄露答案。"),
        ("user", "主题：{topic}\n刚才的讲解：{explanation}"),
    ]
)

ASSESSMENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "严格评价理解程度，不要因为表达流畅就给高分。"),
        (
            "user",
            """主题：{topic}
题目：{quiz_question}
回答：{quiz_answer}
给出 0 到 100 分、具体反馈，以及一个最主要的知识缺口。""",
        ),
    ]
)

SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "你是技术学习教练。用三句话生成诚实、具体的学习小结。"),
        (
            "user",
            """主题：{topic}
最终得分：{score}
反馈：{feedback}
知识缺口：{missing_point}
说明已经理解什么、还缺什么、下一步练什么。""",
        ),
    ]
)


def _as_runnable(model: Any) -> Runnable[Any, Any]:
    if isinstance(model, Runnable):
        return model

    def invoke(value: Any) -> Any:
        model_input = value.to_messages() if hasattr(value, "to_messages") else value
        return model.invoke(model_input)

    return RunnableLambda(invoke)


def _validate_as(schema: type[BaseModel]) -> Runnable[Any, BaseModel]:
    def validate(value: Any) -> BaseModel:
        return value if isinstance(value, schema) else schema.model_validate(value)

    return RunnableLambda(validate)


def _diagnostic_input(values: TaskInput) -> dict[str, list[HumanMessage]]:
    text = f"主题：{values['topic']}。请用一道应用题判断学习者的基础。"
    images = list(values.get("diagnostic_images", ()))
    content: str | list[dict[str, Any]] = text
    if images:
        content = [{"type": "text", "text": text}, *images]
    return {"diagnostic_messages": [HumanMessage(content=content)]}


def _structured_chain(
    prompt: ChatPromptTemplate,
    model: Any,
    schema: type[BaseModel],
    *,
    input_adapter: Runnable[Any, Any] | None = None,
) -> Runnable[Any, Any]:
    chain: Runnable[Any, Any] = prompt | _as_runnable(model) | _validate_as(schema)
    return input_adapter | chain if input_adapter is not None else chain


def _text_chain(
    prompt: ChatPromptTemplate,
    model: Any,
) -> Runnable[TaskInput, str]:
    return prompt | _as_runnable(model) | StrOutputParser()


def _with_optional_fallback(
    primary: Runnable[Any, Any],
    fallback: Runnable[Any, Any] | None,
) -> Runnable[Any, Any]:
    return primary.with_fallbacks([fallback]) if fallback is not None else primary


@dataclass(frozen=True)
class LearningCoachRunnables:
    """Reusable LCEL tasks used by the learning workflow nodes."""

    diagnostic: Runnable[TaskInput, Diagnostic]
    teaching: Runnable[TaskInput, str]
    quiz: Runnable[TaskInput, str]
    assessment: Runnable[TaskInput, Assessment]
    summary: Runnable[TaskInput, str]

    @classmethod
    def from_models(cls, models: LearningCoachModels) -> "LearningCoachRunnables":
        diagnostic_adapter = RunnableLambda(_diagnostic_input)
        diagnostic_primary = _structured_chain(
            DIAGNOSTIC_PROMPT,
            models.diagnostic,
            Diagnostic,
            input_adapter=diagnostic_adapter,
        )
        diagnostic_fallback = (
            _structured_chain(
                DIAGNOSTIC_PROMPT,
                models.diagnostic_fallback,
                Diagnostic,
                input_adapter=diagnostic_adapter,
            )
            if models.diagnostic_fallback is not None
            else None
        )

        assessment_primary = _structured_chain(
            ASSESSMENT_PROMPT, models.assessment, Assessment
        )
        assessment_fallback = (
            _structured_chain(
                ASSESSMENT_PROMPT, models.assessment_fallback, Assessment
            )
            if models.assessment_fallback is not None
            else None
        )

        teaching_primary = _text_chain(TEACHING_PROMPT, models.chat)
        quiz_primary = _text_chain(QUIZ_PROMPT, models.chat)
        summary_primary = _text_chain(SUMMARY_PROMPT, models.chat)
        teaching_fallback = (
            _text_chain(TEACHING_PROMPT, models.chat_fallback)
            if models.chat_fallback is not None
            else None
        )
        quiz_fallback = (
            _text_chain(QUIZ_PROMPT, models.chat_fallback)
            if models.chat_fallback is not None
            else None
        )
        summary_fallback = (
            _text_chain(SUMMARY_PROMPT, models.chat_fallback)
            if models.chat_fallback is not None
            else None
        )

        return cls(
            diagnostic=_with_optional_fallback(
                diagnostic_primary, diagnostic_fallback
            ),
            teaching=_with_optional_fallback(teaching_primary, teaching_fallback),
            quiz=_with_optional_fallback(quiz_primary, quiz_fallback),
            assessment=_with_optional_fallback(
                assessment_primary, assessment_fallback
            ),
            summary=_with_optional_fallback(summary_primary, summary_fallback),
        )
