const setupView = document.querySelector("#setup-view");
const sessionView = document.querySelector("#session-view");
const startForm = document.querySelector("#start-form");
const answerForm = document.querySelector("#answer-form");
const topicInput = document.querySelector("#topic");
const learningGoalInput = document.querySelector("#learning-goal");
const imageInput = document.querySelector("#image");
const studyMaterialInput = document.querySelector("#study-material");
const uploadTitle = document.querySelector("#upload-title");
const setupError = document.querySelector("#setup-error");
const answerInput = document.querySelector("#answer");
const answerError = document.querySelector("#answer-error");
const timeline = document.querySelector("#timeline");
const resultCard = document.querySelector("#result-card");
const answerCard = document.querySelector("#answer-form");
const modelPill = document.querySelector("#model-pill");
const modelLabel = document.querySelector("#model-label");
const panelStatus = document.querySelector("#panel-status");
const messageTemplate = document.querySelector("#message-template");
const cancelStartButton = document.querySelector("#cancel-start");
const cancelRunButton = document.querySelector("#cancel-run");
const contextGoal = document.querySelector("#context-goal");
const contextMastery = document.querySelector("#context-mastery");
const contextBudget = document.querySelector("#context-budget");

let sessionId = null;
let activeController = null;

function errorDetail(error) {
  const detail = error?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) return detail[0].msg;
  return "请求没有完成，请稍后重试。";
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw payload;
  return payload;
}

async function requestStream(url, options, onEvent) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw payload;
  }
  if (!response.body) throw { detail: "浏览器不支持流式响应。" };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      let event = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        if (line.startsWith("data: ")) dataLines.push(line.slice(6));
      }
      if (dataLines.length) onEvent(event, JSON.parse(dataLines.join("\n")));
    }
    if (done) break;
  }
}

function setLoading(form, isLoading) {
  form.classList.toggle("loading", isLoading);
  form.querySelectorAll("button, input, textarea").forEach((element) => {
    element.disabled = isLoading;
  });
}

function addMessage(kind, label, text) {
  const message = messageTemplate.content.firstElementChild.cloneNode(true);
  message.classList.add(kind);
  message.querySelector(".message-meta").textContent = label;
  message.querySelector(".message-body").textContent = text;
  timeline.append(message);
  message.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function streamMessage(task, streamedMessages) {
  if (streamedMessages.has(task)) return streamedMessages.get(task);
  const labels = {
    teaching: "针对性讲解 · 流式生成",
    quiz: "迁移练习 · 流式生成",
    summary: "学习小结 · 流式生成",
  };
  const message = messageTemplate.content.firstElementChild.cloneNode(true);
  message.classList.add("coach");
  message.querySelector(".message-meta").textContent = labels[task] || task;
  timeline.append(message);
  streamedMessages.set(task, message.querySelector(".message-body"));
  return streamedMessages.get(task);
}

function sourceText(sources) {
  return sources
    .map((source) => `[${source.source_id}] ${source.text}`)
    .join("\n\n");
}

function setProgress(stage, completed = false) {
  const order = ["diagnostic", "teach", "quiz", "assessment", "summary"];
  const normalizedStage = stage === "teaching" ? "teach" : stage;
  const activeIndex = completed ? order.length : order.indexOf(normalizedStage);
  document.querySelectorAll("#progress-list li").forEach((item, index) => {
    item.classList.toggle("done", index < activeIndex || completed);
    item.classList.toggle("active", !completed && index === activeIndex);
  });
  const labels = {
    diagnostic: "正在诊断基础",
    teach: "正在针对薄弱点讲解",
    quiz: "等待练习回答",
    assessment: "正在评价掌握程度",
    summary: "学习闭环已完成",
  };
  panelStatus.textContent = labels[normalizedStage] || "学习进行中";
}

function updateContextInsight(data) {
  contextGoal.textContent = data.learning_goal || `掌握主题：${data.topic}`;
  contextMastery.textContent = `掌握度 ${data.mastery_level ?? data.score ?? 0} / 100`;
  const report = data.context_report;
  contextBudget.textContent = report
    ? `${report.mode.toUpperCase()} · 模型 ${report.model_calls}/${report.model_call_limit} · 工具 ${report.tool_calls}/${report.tool_call_limit}`
    : "预算将在讲解后显示";
  if (data.context_summary) contextGoal.title = data.context_summary;
}

function showQuestion(data, streamedTasks = new Set()) {
  updateContextInsight(data);
  if (data.stage === "diagnostic") {
    addMessage("coach", "诊断问题", data.question);
    setProgress("diagnostic");
    return;
  }

  if (data.score !== null && data.score !== undefined && data.attempts > 0) {
    addMessage(
      "assessment",
      `第 ${data.attempts} 次评价 · ${data.score} 分`,
      `${data.feedback}\n\n主要缺口：${data.missing_point}`,
    );
  }
  if (data.sources?.length && !streamedTasks.has("sources")) {
    addMessage("assessment", "本轮参考资料", sourceText(data.sources));
  }
  if (data.explanation && !streamedTasks.has("teaching")) {
    addMessage("coach", "针对性讲解", data.explanation);
  }
  if (!streamedTasks.has("quiz")) {
    addMessage("coach", data.attempts ? "补救练习" : "迁移练习", data.question);
  }
  setProgress("quiz");
}

function showResult(data) {
  updateContextInsight(data);
  if (data.feedback) {
    addMessage(
      "assessment",
      `最终评价 · ${data.score} 分`,
      `${data.feedback}\n\n主要缺口：${data.missing_point}`,
    );
  }
  answerCard.hidden = true;
  resultCard.hidden = false;
  document.querySelector("#result-score").textContent = data.score ?? "—";
  document.querySelector("#result-feedback").textContent = data.feedback || "暂无";
  document.querySelector("#result-missing").textContent = data.missing_point || "暂无";
  document.querySelector("#result-summary").textContent = data.summary || "暂无";
  setProgress("summary", true);
  resultCard.scrollIntoView({ behavior: "smooth", block: "center" });
}

startForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setupError.textContent = "";
  setLoading(startForm, true);
  const formData = new FormData();
  formData.append("topic", topicInput.value);
  if (learningGoalInput.value.trim()) {
    formData.append("learning_goal", learningGoalInput.value);
  }
  if (imageInput.files[0]) formData.append("image", imageInput.files[0]);
  if (studyMaterialInput.value.trim()) {
    formData.append("study_material", studyMaterialInput.value);
  }
  activeController = new AbortController();
  cancelStartButton.hidden = false;
  cancelStartButton.disabled = false;
  let finalState = null;

  try {
    await requestStream(
      "/api/sessions/stream",
      { method: "POST", body: formData, signal: activeController.signal },
      (eventName, payload) => {
        if (eventName === "status") setProgress(payload.task);
        if (eventName === "state") finalState = payload;
        if (eventName === "error") throw { detail: payload.message };
      },
    );
    if (!finalState) throw { detail: "模型运行没有返回最终状态。" };
    sessionId = finalState.session_id;
    setupView.hidden = true;
    sessionView.hidden = false;
    document.querySelector("#session-topic").textContent = finalState.topic;
    showQuestion(finalState);
    answerInput.focus();
  } catch (error) {
    setupError.textContent = error.name === "AbortError" ? "已停止本次生成。" : errorDetail(error);
  } finally {
    activeController = null;
    cancelStartButton.hidden = true;
    setLoading(startForm, false);
  }
});

answerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const answer = answerInput.value.trim();
  if (!answer) return;
  answerError.textContent = "";
  addMessage("user", "你的回答", answer);
  answerInput.value = "";
  setProgress("assessment");
  setLoading(answerForm, true);
  activeController = new AbortController();
  cancelRunButton.hidden = false;
  cancelRunButton.disabled = false;
  const streamedMessages = new Map();
  const streamedTasks = new Set();
  let finalState = null;

  try {
    await requestStream(
      `/api/sessions/${sessionId}/answers/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer }),
        signal: activeController.signal,
      },
      (eventName, payload) => {
        if (eventName === "status") setProgress(payload.task);
        if (eventName === "token") {
          streamedTasks.add(payload.task);
          const body = streamMessage(payload.task, streamedMessages);
          body.textContent += payload.text;
          body.parentElement.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        if (eventName === "sources" && payload.sources?.length) {
          streamedTasks.add("sources");
          addMessage("assessment", "本轮参考资料", sourceText(payload.sources));
        }
        if (eventName === "state") finalState = payload;
        if (eventName === "error") throw { detail: payload.message };
      },
    );
    if (!finalState) throw { detail: "模型运行没有返回最终状态。" };
    if (finalState.status === "completed") showResult(finalState);
    else showQuestion(finalState, streamedTasks);
  } catch (error) {
    answerError.textContent = error.name === "AbortError" ? "已停止本次生成，可以重新提交。" : errorDetail(error);
    answerInput.value = answer;
  } finally {
    activeController = null;
    cancelRunButton.hidden = true;
    setLoading(answerForm, false);
    if (!answerCard.hidden) answerInput.focus();
  }
});

function cancelActiveRun() {
  activeController?.abort();
}

cancelStartButton.addEventListener("click", cancelActiveRun);
cancelRunButton.addEventListener("click", cancelActiveRun);

answerInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    answerForm.requestSubmit();
  }
});

imageInput.addEventListener("change", () => {
  const file = imageInput.files[0];
  uploadTitle.textContent = file ? file.name : "附一张题目或流程图";
});

document.querySelector("#restart-button").addEventListener("click", () => {
  sessionId = null;
  timeline.replaceChildren();
  resultCard.hidden = true;
  answerCard.hidden = false;
  sessionView.hidden = true;
  setupView.hidden = false;
  answerInput.value = "";
  activeController?.abort();
  activeController = null;
  document.querySelectorAll("#progress-list li").forEach((item) => {
    item.classList.remove("active", "done");
  });
  panelStatus.textContent = "等待开始";
  contextGoal.textContent = "等待学习目标";
  contextMastery.textContent = "掌握度 0 / 100";
  contextBudget.textContent = "预算将在讲解后显示";
  topicInput.focus();
});

request("/api/config")
  .then((config) => {
    if (!config.configured) throw { detail: config.error };
    modelPill.classList.add("ready");
    const sameModel = config.chat_model_id === config.assessment_model_id;
    const primaryLabel = sameModel
      ? config.chat_model_id
      : `${config.chat_model_id} · 评价 ${config.assessment_model_id}`;
    const fallbackModels = [
      config.chat_fallback_model_id,
      config.assessment_fallback_model_id,
    ].filter((model, index, models) => model && models.indexOf(model) === index);
    modelLabel.textContent = fallbackModels.length
      ? `${primaryLabel} · 备用 ${fallbackModels.join(" / ")}`
      : primaryLabel;
    if (!config.accepts_images) {
      imageInput.disabled = true;
      uploadTitle.textContent = "当前模型未声明图片能力";
    }
  })
  .catch((error) => {
    modelPill.classList.add("error");
    modelLabel.textContent = "模型尚未配置";
    setupError.textContent = errorDetail(error);
    startForm.querySelector("button[type='submit']").disabled = true;
  });
