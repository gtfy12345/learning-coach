from typing import Any, Literal

from langgraph.types import interrupt

from learning_coach.model import LearningCoachModels
from learning_coach.schemas import Assessment, Diagnostic
from learning_coach.state import LearningState


def _message_text(message: Any) -> str:
    """Read plain text from current and compatible LangChain messages."""

    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)


def route_after_assessment(state: LearningState) -> Literal["retry", "finish"]:
    """Choose a bounded retry so the graph cannot loop forever."""

    if state["score"] >= 80 or state.get("attempts", 0) >= 2:
        return "finish"
    return "retry"


class LearningCoachNodes:
    """Nodes that perform one learning task and return partial state updates."""

    def __init__(self, models: LearningCoachModels | Any) -> None:
        self.models = (
            models
            if isinstance(models, LearningCoachModels)
            else LearningCoachModels.from_models(models)
        )

    def make_diagnostic(self, state: LearningState) -> dict[str, str]:
        prompt = f"主题：{state['topic']}。请用一道应用题判断学习者的基础。"
        images = state.get("diagnostic_images", [])
        user_content: str | list[dict[str, Any]] = prompt
        if images:
            user_content = [{"type": "text", "text": prompt}, *images]

        result = self.models.diagnostic.invoke(
            [
                ("system", "你是技术学习教练。只出一道诊断题，不要给答案。"),
                {"role": "user", "content": user_content},
            ]
        )
        diagnostic = (
            result if isinstance(result, Diagnostic) else Diagnostic.model_validate(result)
        )
        return {
            "diagnostic_question": diagnostic.question,
            "diagnostic_focus": diagnostic.focus,
            "diagnostic_difficulty": diagnostic.difficulty,
        }

    def collect_diagnostic(self, state: LearningState) -> dict[str, Any]:
        answer = interrupt(
            {
                "kind": "diagnostic",
                "question": state["diagnostic_question"],
            }
        )
        return {"diagnostic_answer": str(answer), "attempts": 0}

    def teach(self, state: LearningState) -> dict[str, str]:
        explanation = self.models.chat.invoke(
            [
                (
                    "system",
                    "你是技术学习教练。针对薄弱点讲解，并使用一个具体代码场景。",
                ),
                (
                    "user",
                    f"""主题：{state['topic']}
诊断重点：{state.get('diagnostic_focus', '暂无')}
诊断难度：{state.get('diagnostic_difficulty', '暂无')}
诊断回答：{state.get('diagnostic_answer', '暂无')}
上次反馈：{state.get('feedback', '暂无')}
尚未掌握：{state.get('missing_point', '暂无')}
请控制在 300 字内，不要只重复定义。""",
                ),
            ]
        )
        return {"explanation": _message_text(explanation)}

    def make_quiz(self, state: LearningState) -> dict[str, str]:
        question = self.models.chat.invoke(
            [
                ("system", "只出一道新的应用题，不要泄露答案。"),
                (
                    "user",
                    f"主题：{state['topic']}\n刚才的讲解：{state['explanation']}",
                ),
            ]
        )
        return {"quiz_question": _message_text(question)}

    def collect_quiz(self, state: LearningState) -> dict[str, str]:
        answer = interrupt(
            {
                "kind": "quiz",
                "question": state["quiz_question"],
            }
        )
        return {"quiz_answer": str(answer)}

    def assess(self, state: LearningState) -> dict[str, Any]:
        result = self.models.assessment.invoke(
            [
                (
                    "system",
                    "严格评价理解程度，不要因为表达流畅就给高分。",
                ),
                (
                    "user",
                    f"""主题：{state['topic']}
题目：{state['quiz_question']}
回答：{state['quiz_answer']}
给出 0 到 100 分、具体反馈，以及一个最主要的知识缺口。""",
                ),
            ]
        )
        assessment = (
            result if isinstance(result, Assessment) else Assessment.model_validate(result)
        )
        return {
            "score": assessment.score,
            "feedback": assessment.feedback,
            "missing_point": assessment.missing_point,
            "attempts": state.get("attempts", 0) + 1,
        }

    def summarize(self, state: LearningState) -> dict[str, str]:
        summary = self.models.chat.invoke(
            [
                (
                    "system",
                    "你是技术学习教练。用三句话生成诚实、具体的学习小结。",
                ),
                (
                    "user",
                    f"""主题：{state['topic']}
最终得分：{state['score']}
反馈：{state['feedback']}
知识缺口：{state['missing_point']}
说明已经理解什么、还缺什么、下一步练什么。""",
                ),
            ]
        )
        return {"summary": _message_text(summary)}
