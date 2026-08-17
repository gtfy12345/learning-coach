const setupView = document.querySelector("#setup-view");
const sessionView = document.querySelector("#session-view");
const startForm = document.querySelector("#start-form");
const answerForm = document.querySelector("#answer-form");
const topicInput = document.querySelector("#topic");
const learningGoalInput = document.querySelector("#learning-goal");
const learningModeInput = document.querySelector("#learning-mode");
const imageInput = document.querySelector("#image");
const studyMaterialInput = document.querySelector("#study-material");
const materialsInput = document.querySelector("#materials");
const materialsTitle = document.querySelector("#materials-title");
const sourceUrlsInput = document.querySelector("#source-urls");
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
const contextIngestion = document.querySelector("#context-ingestion");
const contextRetrieval = document.querySelector("#context-retrieval");
const contextEvents = document.querySelector("#context-events");
const contextMemory = document.querySelector("#context-memory");
const timeTravelPanel = document.querySelector("#time-travel");
const forkBanner = document.querySelector("#fork-banner");
const milestoneList = document.querySelector("#milestone-list");
const approvalActions = document.querySelector("#approval-actions");
const approveButton = document.querySelector("#approve-button");
const rejectButton = document.querySelector("#reject-button");
const learnerIdInput = document.querySelector("#learner-id");
const conceptGraphCard = document.querySelector("#concept-graph-card");
const conceptGraphMeta = document.querySelector("#concept-graph-meta");
const conceptGraphNodes = document.querySelector("#concept-graph-nodes");
const conceptRelations = document.querySelector("#concept-relations");
const prerequisiteList = document.querySelector("#prerequisite-list");
const codePracticeCard = document.querySelector("#code-practice-card");
const codePracticeTitle = document.querySelector("#code-practice-title");
const codePracticeMeta = document.querySelector("#code-practice-meta");
const codePracticeInstructions = document.querySelector("#code-practice-instructions");
const codeStarter = document.querySelector("#code-starter");
const codeTestResults = document.querySelector("#code-test-results");
const codeHints = document.querySelector("#code-hints");
const codeSafetyNotice = document.querySelector("#code-safety-notice");

let sessionId = null;
let activeController = null;
let currentCodeExercise = null;
let currentLearningMode = "teach_first";

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
  form.querySelectorAll("button, input, textarea, select").forEach((element) => {
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
    .map((source) => {
      const label = [source.source_name, source.location].filter(Boolean).join(" · ");
      const score = source.retrieval_score?.graph_fusion
        ?? source.retrieval_score?.rerank
        ?? source.score;
      const relevance = Number.isFinite(score)
        ? ` · 相关度 ${Math.round(score * 100)}%`
        : "";
      return `[${label || source.source_id}${relevance}] ${source.text}`;
    })
    .join("\n\n");
}

function renderKnowledgeGraph(report) {
  const nodes = Array.isArray(report?.nodes) ? report.nodes : [];
  const relations = Array.isArray(report?.relations) ? report.relations : [];
  const prerequisites = Array.isArray(report?.prerequisites)
    ? report.prerequisites
    : [];
  const meaningful = nodes.length > 0 && (relations.length > 0 || prerequisites.length > 0);
  conceptGraphCard.hidden = !meaningful;
  conceptGraphNodes.replaceChildren();
  conceptRelations.replaceChildren();
  prerequisiteList.replaceChildren();
  if (!meaningful) return;

  const extractionLabels = {
    deterministic: "离线抽取",
    model_augmented: "模型增强",
    fallback: "安全降级",
  };
  conceptGraphMeta.textContent = `${nodes.length} 个概念 · ${relations.length} 条关系 · ${extractionLabels[report.extraction_mode] || report.extraction_mode}`;
  const nodeNames = new Map(nodes.map((node) => [node.concept_id, node.name]));

  nodes.slice(0, 24).forEach((node) => {
    const chip = document.createElement("span");
    chip.className = `concept-node concept-node-${node.kind}`;
    chip.textContent = node.name;
    chip.title = node.aliases?.length ? `别名：${node.aliases.join("、")}` : node.kind;
    conceptGraphNodes.append(chip);
  });

  const relationLabels = {
    prerequisite_of: "是前置知识 →",
    part_of: "组成 →",
    related_to: "关联 ↔",
  };
  relations.slice(0, 20).forEach((relation) => {
    const row = document.createElement("div");
    row.className = "concept-relation";
    const source = nodeNames.get(relation.from_concept_id) || "未知概念";
    const target = nodeNames.get(relation.to_concept_id) || "未知概念";
    row.textContent = `${source} ${relationLabels[relation.relation_type] || relation.relation_type} ${target}`;
    conceptRelations.append(row);
  });

  prerequisites.forEach((item) => {
    const entry = document.createElement("li");
    const path = document.createElement("strong");
    path.textContent = item.path_names.join(" → ");
    const reason = document.createElement("p");
    reason.textContent = item.reason;
    entry.append(path, reason);
    if (item.evidence_locations?.length) {
      const locations = document.createElement("small");
      locations.textContent = `依据：${item.evidence_locations.join("；")}`;
      entry.append(locations);
    }
    prerequisiteList.append(entry);
  });
}

function renderCodePractice(data) {
  const exercise = data?.code_exercise || data?.exercise || null;
  const report = data?.code_practice_report || data?.report || null;
  currentCodeExercise = exercise;
  codePracticeCard.hidden = !exercise && !report;
  codeTestResults.replaceChildren();
  codeHints.replaceChildren();
  if (!exercise && !report) return;

  if (exercise) {
    codePracticeTitle.textContent = exercise.title;
    codePracticeMeta.textContent = `${exercise.entrypoint} · ${exercise.total_test_count} 个测试`;
    codePracticeInstructions.textContent = exercise.instructions;
    codeStarter.textContent = exercise.starter_code;
    if (!answerInput.value.trim()) answerInput.value = exercise.starter_code;
    answerInput.placeholder = "提交完整 Python 函数代码；⌘/Ctrl + Enter 运行测试。";
  }
  if (report) {
    codePracticeMeta.textContent = `${report.passed_tests}/${report.total_tests} 通过 · ${report.error_type}`;
    report.outcomes.forEach((outcome) => {
      const item = document.createElement("li");
      item.className = `code-test-${outcome.status}`;
      item.textContent = `${outcome.test_id} · ${outcome.status} · ${outcome.summary}`;
      codeTestResults.append(item);
    });
    report.hints.forEach((hint) => {
      const item = document.createElement("li");
      const label = document.createElement("strong");
      const text = document.createElement("span");
      label.textContent = `提示 ${hint.level}`;
      text.textContent = hint.text;
      item.append(label, text);
      codeHints.append(item);
    });
    codeSafetyNotice.textContent = report.safety_notice;
  } else {
    codeSafetyNotice.textContent = "测试由本地受限执行器运行；它不是面向恶意代码的强隔离沙箱。";
  }
}

function retrievalText(report) {
  if (!report) return "检索将在讲解时运行";
  const quality = {
    sufficient: "证据充足",
    insufficient: "证据不足",
    empty: "没有命中",
  }[report.quality] || report.quality;
  const rewritten = report.rewritten ? " · 已改写查询" : "";
  return `Hybrid RAG · ${report.attempts.length}/2 次 · ${quality}${rewritten}`;
}

function setProgress(stage, completed = false) {
  const order = currentLearningMode === "diagnose_first"
    ? ["diagnostic", "teach", "quiz", "assessment", "summary"]
    : ["teach", "understanding_check", "quiz", "assessment", "summary"];
  const normalizedStage = stage === "teaching" ? "teach" : stage;
  const activeIndex = completed ? order.length : order.indexOf(normalizedStage);
  document.querySelectorAll("#progress-list li").forEach((item) => {
    const itemIndex = order.indexOf(item.dataset.step);
    item.hidden = itemIndex < 0;
    if (itemIndex < 0) return;
    item.classList.toggle("done", itemIndex < activeIndex || completed);
    item.classList.toggle("active", !completed && itemIndex === activeIndex);
  });
  const labels = {
    diagnostic: "正在诊断基础",
    teach: "正在针对薄弱点讲解",
    understanding_check: "等待理解检查回答",
    quiz: "等待练习回答",
    assessment: "正在评价掌握程度",
    summary: "学习闭环已完成",
  };
  panelStatus.textContent = labels[normalizedStage] || "学习进行中";
}

function learningEventsText(data) {
  const events = data.learning_events || [];
  const handoffs = data.agent_handoffs || [];
  const reviews = data.teaching_reviews || [];
  const plan = data.teaching_plan;
  if (!events.length && !handoffs.length) {
    return "Agent 轨迹将在教学开始后显示";
  }
  const labels = {
    teach: "讲解",
    teach_initial: "基础教学",
    assess_understanding: "理解检查",
    prepare_practice: "练习准备",
    assess: "评价",
    recall_memory: "记忆召回",
    remember_session: "记忆保存",
    approve_execution: "执行审批",
  };
  const kind =
    data.practice_kind === "code"
      ? "代码练习"
      : data.practice_kind === "text"
        ? "文本练习"
        : "练习待定";
  const foci = plan?.research_foci?.length
    ? ` · 研究焦点 ${plan.research_foci.length}`
    : "";
  const reviewSummary = reviews.length
    ? ` · 审查 ${reviews.filter((r) => r.passed).length}/${reviews.length} 通过`
    : "";
  const parts = events.slice(-6).map((event) => {
    const label = labels[event.node] || event.node;
    return `${label}：${event.detail || event.status}`;
  });
  return (
    `${kind}${foci}${reviewSummary} · 交接 ${handoffs.length} 次` +
    `（顺序不保证）：${parts.join("｜")}`
  );
}

function updateContextInsight(data) {
  contextGoal.textContent = data.learning_goal || `掌握主题：${data.topic}`;
  contextMastery.textContent = `掌握度 ${data.mastery_level ?? data.score ?? 0} / 100`;
  const report = data.context_report;
  contextBudget.textContent = report
    ? `${report.mode.toUpperCase()} · 模型 ${report.model_calls}/${report.model_call_limit} · 工具 ${report.tool_calls}/${report.tool_call_limit}`
    : "预算将在讲解后显示";
  const ingestion = data.ingestion_report;
  contextIngestion.textContent = ingestion
    ? `资料 ${ingestion.sources_received} 个 · 新增 ${ingestion.sources_added} · 更新 ${ingestion.sources_updated} · 跳过 ${ingestion.sources_skipped}`
    : "尚未摄取学习资料";
  contextRetrieval.textContent = retrievalText(data.retrieval_report);
  contextEvents.textContent = learningEventsText(data);
  const memory = data.long_term_memory;
  contextMemory.textContent = memory?.sessions
    ? `长期记忆 ${memory.sessions} 次 · 平均 ${memory.average_score} 分${memory.last_topic ? ` · 上次：${memory.last_topic}` : ""}`
    : "长期记忆将在会话开始后显示";
  if (data.graph_report?.graph_used) {
    contextRetrieval.textContent += ` · GraphRAG ${data.graph_report.prerequisites.length} 条前置路径`;
  }
  renderKnowledgeGraph(data.graph_report);
  renderCodePractice(data);
  if (data.context_summary) contextGoal.title = data.context_summary;
}

function showQuestion(data, streamedTasks = new Set()) {
  currentLearningMode = data.learning_mode || currentLearningMode;
  updateContextInsight(data);
  refreshMilestones();
  approvalActions.hidden = data.stage !== "approval";
  if (data.stage === "diagnostic") {
    addMessage("coach", "诊断问题", data.question);
    setProgress("diagnostic");
    return;
  }

  if (data.stage === "understanding_check") {
    if (data.sources?.length && !streamedTasks.has("sources")) {
      addMessage("assessment", "本轮参考资料", sourceText(data.sources));
    }
    if (data.explanation && !streamedTasks.has("teaching")) {
      addMessage("coach", "基础教学", data.explanation);
    }
    addMessage("coach", "理解检查", data.question);
    answerInput.placeholder = "用自己的话说明你的理解；不确定也没关系。";
    setProgress("understanding_check");
    return;
  }

  if (data.stage === "approval") {
    addMessage("coach", "执行审批", `${data.question}\n\n请选择批准或拒绝；拒绝不会运行任何测试。`);
    setProgress("assessment");
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
  approvalActions.hidden = true;
  refreshMilestones();
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
  const stageCard = document.querySelector("#stage-report-card");
  const report = data.stage_report;
  if (report) {
    stageCard.hidden = false;
    document.querySelector("#stage-report-summary").textContent = report.summary || "";
    const bands = { weak: "薄弱", practiced: "已练", introduced: "引入" };
    const mastery = (report.mastery?.concepts || [])
      .slice(0, 6)
      .map((concept) => `${concept.name}（${bands[concept.band] || concept.band}）`)
      .join("、");
    document.querySelector("#stage-report-mastery").textContent =
      mastery ? `掌握图谱：${mastery}` : "掌握图谱：暂无概念";
    const next = (report.mastery?.recommended_next || []).slice(0, 2).join("；");
    document.querySelector("#stage-report-next").textContent = next ? `下一步：${next}` : "";
  } else {
    stageCard.hidden = true;
  }
  setProgress("summary", true);
  resultCard.scrollIntoView({ behavior: "smooth", block: "center" });
}

startForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setupError.textContent = "";
  currentLearningMode = learningModeInput.value;
  setLoading(startForm, true);
  const formData = new FormData();
  formData.append("topic", topicInput.value);
  formData.append("learning_mode", learningModeInput.value);
  if (learningGoalInput.value.trim()) {
    formData.append("learning_goal", learningGoalInput.value);
  }
  if (learnerIdInput.value.trim()) {
    formData.append("learner_id", learnerIdInput.value);
  }
  if (imageInput.files[0]) formData.append("image", imageInput.files[0]);
  if (studyMaterialInput.value.trim()) {
    formData.append("study_material", studyMaterialInput.value);
  }
  for (const material of materialsInput.files) {
    formData.append("materials", material);
  }
  if (sourceUrlsInput.value.trim()) {
    formData.append("source_urls", sourceUrlsInput.value);
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
    currentLearningMode = finalState.learning_mode || learningModeInput.value;
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

async function submitAnswerStream(answer, echoLabel) {
  answerError.textContent = "";
  if (echoLabel) addMessage("user", echoLabel, answer);
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
        if (eventName === "retrieval" && payload.report) {
          contextRetrieval.textContent = retrievalText(payload.report);
        }
        if (eventName === "knowledge_graph" && payload.report) {
          renderKnowledgeGraph(payload.report);
        }
        if (eventName === "code_practice") {
          renderCodePractice(payload);
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
}

answerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const answer = answerInput.value.trim();
  if (!answer) return;
  await submitAnswerStream(answer, currentCodeExercise ? "你的代码" : "你的回答");
});

approveButton.addEventListener("click", () => {
  if (approvalActions.hidden) return;
  submitAnswerStream("approve", "审批决定");
});

rejectButton.addEventListener("click", () => {
  if (approvalActions.hidden) return;
  submitAnswerStream("reject", "审批决定");
});

async function refreshMilestones() {
  if (!sessionId) return;
  try {
    const milestones = await request(`/api/sessions/${sessionId}/history`);
    timeTravelPanel.hidden = false;
    milestoneList.replaceChildren();
    for (const milestone of milestones.slice(0, 8)) {
      const item = document.createElement("div");
      item.className = "milestone-item";
      const label = document.createElement("span");
      const parts = [milestone.label];
      if (milestone.score !== null && milestone.score !== undefined) {
        parts.push(`${milestone.score} 分`);
      }
      if (milestone.attempts) parts.push(`第 ${milestone.attempts} 次评价`);
      label.textContent = parts.join(" · ");
      item.append(label);
      if (milestone.forkable) {
        const forkButton = document.createElement("button");
        forkButton.type = "button";
        forkButton.className = "text-button";
        forkButton.textContent = "分叉";
        forkButton.addEventListener("click", () => forkFromCheckpoint(milestone));
        item.append(forkButton);
      }
      milestoneList.append(item);
    }
  } catch {
    timeTravelPanel.hidden = true;
  }
}

function comparisonText(comparison) {
  const entries = Object.entries(comparison || {});
  if (!entries.length) return "暂无差异";
  return entries
    .slice(0, 3)
    .map(([field, diff]) => `${field}: ${JSON.stringify(diff.before)} → ${JSON.stringify(diff.after)}`)
    .join("；");
}

async function forkFromCheckpoint(milestone) {
  try {
    const payload = await request(`/api/sessions/${sessionId}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ checkpoint_id: milestone.checkpoint_id }),
    });
    sessionId = payload.session.session_id;
    forkBanner.hidden = false;
    forkBanner.textContent = `已从「${milestone.label}」分叉出新会话 · 基线对比：${comparisonText(payload.comparison)}`;
    if (payload.session.status === "completed") showResult(payload.session);
    else showQuestion(payload.session);
  } catch (error) {
    answerError.textContent = errorDetail(error);
  }
}

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

materialsInput.addEventListener("change", () => {
  const files = Array.from(materialsInput.files);
  if (!files.length) {
    materialsTitle.textContent = "上传论文、书籍、课件、图片或代码";
    return;
  }
  const preview = files.slice(0, 2).map((file) => file.name).join("、");
  materialsTitle.textContent = files.length > 2
    ? `已选择 ${files.length} 个资料：${preview}…`
    : `已选择：${preview}`;
});

document.querySelector("#restart-button").addEventListener("click", () => {
  sessionId = null;
  currentLearningMode = learningModeInput.value;
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
  contextIngestion.textContent = "尚未摄取学习资料";
  contextRetrieval.textContent = "检索将在讲解时运行";
  renderKnowledgeGraph(null);
  renderCodePractice(null);
  answerInput.placeholder = "用自己的话回答。不确定也没关系。";
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
    modelLabel.textContent += ` · 检索 ${config.embedding_model_id}`;
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
