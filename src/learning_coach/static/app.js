const setupView = document.querySelector("#setup-view");
const sessionView = document.querySelector("#session-view");
const startForm = document.querySelector("#start-form");
const answerForm = document.querySelector("#answer-form");
const topicInput = document.querySelector("#topic");
const imageInput = document.querySelector("#image");
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

let sessionId = null;

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

function setProgress(stage, completed = false) {
  const order = ["diagnostic", "teach", "quiz", "assessment", "summary"];
  const activeIndex = completed ? order.length : order.indexOf(stage);
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
  panelStatus.textContent = labels[stage] || "学习进行中";
}

function showQuestion(data) {
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
  if (data.explanation) addMessage("coach", "针对性讲解", data.explanation);
  addMessage("coach", data.attempts ? "补救练习" : "迁移练习", data.question);
  setProgress("quiz");
}

function showResult(data) {
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
  if (imageInput.files[0]) formData.append("image", imageInput.files[0]);

  try {
    const data = await request("/api/sessions", { method: "POST", body: formData });
    sessionId = data.session_id;
    setupView.hidden = true;
    sessionView.hidden = false;
    document.querySelector("#session-topic").textContent = data.topic;
    showQuestion(data);
    answerInput.focus();
  } catch (error) {
    setupError.textContent = errorDetail(error);
  } finally {
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

  try {
    const data = await request(`/api/sessions/${sessionId}/answers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    if (data.status === "completed") showResult(data);
    else showQuestion(data);
  } catch (error) {
    answerError.textContent = errorDetail(error);
    answerInput.value = answer;
  } finally {
    setLoading(answerForm, false);
    if (!answerCard.hidden) answerInput.focus();
  }
});

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
  document.querySelectorAll("#progress-list li").forEach((item) => {
    item.classList.remove("active", "done");
  });
  panelStatus.textContent = "等待开始";
  topicInput.focus();
});

request("/api/config")
  .then((config) => {
    if (!config.configured) throw { detail: config.error };
    modelPill.classList.add("ready");
    const sameModel = config.chat_model_id === config.assessment_model_id;
    modelLabel.textContent = sameModel
      ? config.chat_model_id
      : `${config.chat_model_id} · 评价 ${config.assessment_model_id}`;
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
