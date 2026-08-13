from dataclasses import dataclass
from collections.abc import AsyncIterator, Iterator
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    Runnable,
    RunnableAssign,
    RunnableLambda,
    RunnableParallel,
    RunnablePassthrough,
    RunnableSequence,
)
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel

from learning_coach.model import LearningCoachModels
from learning_coach.context import LearningRuntimeContext
from learning_coach.middleware import ContextEngineeredTeaching
from learning_coach.retrieval import retrieve_study_sources
from learning_coach.schemas import (
    Assessment,
    Diagnostic,
    GroundedTeaching,
    StudySource,
)

TaskInput = dict[str, Any]
TaskName = Literal["diagnostic", "teaching", "quiz", "assessment", "summary"]


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
            "你是技术学习教练。针对薄弱点讲解，并使用一个具体代码场景。"
            "结合本次学习目标、掌握度、最近错误和学习摘要调整讲解深度。",
        ),
        (
            "user",
            """主题：{topic}
诊断重点：{diagnostic_focus}
诊断难度：{diagnostic_difficulty}
诊断回答：{diagnostic_answer}
上次反馈：{feedback}
尚未掌握：{missing_point}
学习目标：{learning_goal}
当前掌握度：{mastery_level}/100
最近错误：{recent_errors}
学习摘要：
{context_summary}
参考资料：
{study_context}
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


def _teaching_query(values: TaskInput) -> str:
    return " ".join(
        str(values.get(key, ""))
        for key in ("topic", "diagnostic_focus", "feedback", "missing_point")
    ).strip()


def _retrieve_teaching_sources(values: TaskInput) -> list[StudySource]:
    retrieved = retrieve_study_sources(
        {
            "query": _teaching_query(values),
            "study_material": values.get("study_material", ""),
        }
    )
    return [
        StudySource(
            source_id=source.source_id,
            text=source.text,
            score=source.score,
        )
        for source in retrieved
    ]


def _format_study_context(values: TaskInput) -> str:
    sources = values.get("sources", [])
    if not sources:
        return "没有可用参考资料，请基于通用知识讲解，并避免声称引用了资料。"
    return "\n\n".join(
        f"[{source.source_id}] {source.text}"
        for source in sources
        if isinstance(source, StudySource)
    )


def _teaching_prompt_input(values: TaskInput) -> TaskInput:
    task = dict(values["task"])
    task["study_context"] = values["study_context"]
    task.setdefault("learning_goal", f"掌握主题：{task.get('topic', '')}")
    task.setdefault("mastery_level", 0)
    errors = task.get("recent_errors", "暂无")
    if isinstance(errors, list):
        errors = "；".join(str(error) for error in errors) or "暂无"
    task["recent_errors"] = errors
    task.setdefault("context_summary", "暂无")
    return task


def _grounded_teaching(values: TaskInput) -> GroundedTeaching:
    return GroundedTeaching.model_validate(values)


class GroundedTeachingParser(Runnable[TaskInput, GroundedTeaching]):
    """Preserve text chunks while attaching sources to the first chunk."""

    def invoke(
        self,
        input: TaskInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> GroundedTeaching:
        return _grounded_teaching(input)

    def transform(
        self,
        input: Iterator[TaskInput],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[GroundedTeaching]:
        sources: list[StudySource] | None = None
        buffered_text: list[str] = []
        sources_emitted = False
        for chunk in input:
            if "sources" in chunk:
                sources = list(chunk["sources"])
            if "text" in chunk:
                buffered_text.append(str(chunk["text"]))
            if sources is not None and buffered_text:
                for text in buffered_text:
                    yield GroundedTeaching(
                        text=text,
                        sources=sources if not sources_emitted else [],
                    )
                    sources_emitted = True
                buffered_text.clear()
        for text in buffered_text:
            yield GroundedTeaching(
                text=text,
                sources=(sources or []) if not sources_emitted else [],
            )
            sources_emitted = True

    async def atransform(
        self,
        input: AsyncIterator[TaskInput],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[GroundedTeaching]:
        sources: list[StudySource] | None = None
        buffered_text: list[str] = []
        sources_emitted = False
        async for chunk in input:
            if "sources" in chunk:
                sources = list(chunk["sources"])
            if "text" in chunk:
                buffered_text.append(str(chunk["text"]))
            if sources is not None and buffered_text:
                for text in buffered_text:
                    yield GroundedTeaching(
                        text=text,
                        sources=sources if not sources_emitted else [],
                    )
                    sources_emitted = True
                buffered_text.clear()
        for text in buffered_text:
            yield GroundedTeaching(
                text=text,
                sources=(sources or []) if not sources_emitted else [],
            )
            sources_emitted = True


def _grounded_teaching_chain(
    prompt: ChatPromptTemplate,
    model: Any,
) -> Runnable[TaskInput, GroundedTeaching]:
    retrieval = RunnableParallel(
        task=RunnablePassthrough(),
        sources=RunnableLambda(_retrieve_teaching_sources),
    )
    assign_context = RunnableAssign(
        RunnableParallel(
            study_context=RunnableLambda(_format_study_context),
        ),
        name="AssignStudyContext",
    )
    answer = RunnableSequence(
        RunnableLambda(_teaching_prompt_input),
        prompt,
        _as_runnable(model),
        StrOutputParser(),
    )
    return RunnableSequence(
        retrieval,
        assign_context,
        RunnableParallel(
            text=answer,
            sources=RunnableLambda(lambda values: values["sources"]),
        ),
        GroundedTeachingParser(),
    )


def _with_optional_fallback(
    primary: Runnable[Any, Any],
    fallback: Runnable[Any, Any] | None,
) -> Runnable[Any, Any]:
    return primary.with_fallbacks([fallback]) if fallback is not None else primary


def _configured_task(
    name: TaskName,
    runnable: Runnable[Any, Any],
) -> Runnable[Any, Any]:
    return runnable.with_config(
        run_name=f"learning_coach_{name}",
        tags=["learning-coach", f"task:{name}"],
        metadata={"component": "learning-coach", "task": name},
    )


@dataclass(frozen=True)
class LearningCoachRunnables:
    """Reusable LCEL tasks used by the learning workflow nodes."""

    diagnostic: Runnable[TaskInput, Diagnostic]
    teaching: Runnable[TaskInput, GroundedTeaching]
    quiz: Runnable[TaskInput, str]
    assessment: Runnable[TaskInput, Assessment]
    summary: Runnable[TaskInput, str]
    teaching_engine: ContextEngineeredTeaching | None = None

    def teach(
        self,
        task_input: TaskInput,
        runtime: LearningRuntimeContext,
    ) -> GroundedTeaching:
        """Run context-engineered teaching while preserving the legacy Runnable."""

        if self.teaching_engine is None:
            result = self.teaching.invoke(task_input)
            return (
                result
                if isinstance(result, GroundedTeaching)
                else GroundedTeaching.model_validate(result)
            )
        return self.teaching_engine.invoke(task_input, runtime)

    def task(self, name: TaskName | str) -> Runnable[Any, Any]:
        tasks: dict[str, Runnable[Any, Any]] = {
            "diagnostic": self.diagnostic,
            "teaching": self.teaching,
            "quiz": self.quiz,
            "assessment": self.assessment,
            "summary": self.summary,
        }
        try:
            return tasks[name]
        except KeyError as exc:
            choices = ", ".join(tasks)
            raise ValueError(
                f"未知 LCEL 任务：{name}。可选值：{choices}。"
            ) from exc

    def draw_mermaid(self, name: TaskName | str) -> str:
        legend = (
            "%% LCEL composition: RunnableSequence, RunnableParallel, "
            "RunnablePassthrough, RunnableAssign, RunnableLambda\n"
        )
        return legend + self.task(name).get_graph().draw_mermaid()

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

        teaching_primary = _grounded_teaching_chain(TEACHING_PROMPT, models.chat)
        quiz_primary = _text_chain(QUIZ_PROMPT, models.chat)
        summary_primary = _text_chain(SUMMARY_PROMPT, models.chat)
        teaching_fallback = (
            _grounded_teaching_chain(TEACHING_PROMPT, models.chat_fallback)
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

        teaching_task = _configured_task(
            "teaching",
            _with_optional_fallback(teaching_primary, teaching_fallback),
        )
        return cls(
            diagnostic=_configured_task(
                "diagnostic",
                _with_optional_fallback(diagnostic_primary, diagnostic_fallback),
            ),
            teaching=teaching_task,
            quiz=_configured_task(
                "quiz", _with_optional_fallback(quiz_primary, quiz_fallback)
            ),
            assessment=_configured_task(
                "assessment",
                _with_optional_fallback(
                    assessment_primary, assessment_fallback
                ),
            ),
            summary=_configured_task(
                "summary",
                _with_optional_fallback(summary_primary, summary_fallback),
            ),
            teaching_engine=ContextEngineeredTeaching(
                primary_model=models.chat,
                advanced_model=models.advanced_chat,
                fallback_runnable=teaching_task,
            ),
        )
