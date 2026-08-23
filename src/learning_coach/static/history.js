const historyList = document.querySelector("#history-list");
const historyError = document.querySelector("#history-error");
const historyCount = document.querySelector("#history-count");
const historyLearner = document.querySelector("#history-learner");
const learnerInput = document.querySelector("#history-learner-input");
const refreshButton = document.querySelector("#history-refresh");

const MODE_LABELS = {
  teach_first: "先教后测",
  diagnose_first: "先诊断",
};

function escapeText(value) {
  return String(value ?? "");
}

function formatTime(value) {
  const text = escapeText(value);
  return text ? text.replace("T", " ").replace("+00:00", " UTC") : "未知时间";
}

function renderQuestions(questions) {
  historyList.replaceChildren();
  if (!questions.length) {
    const empty = document.createElement("p");
    empty.className = "hero-copy";
    empty.textContent = "还没有历史问题。回到首页提交第一个学习主题。";
    historyList.append(empty);
    return;
  }
  for (const item of questions) {
    const card = document.createElement("article");
    card.className = "history-card";
    const heading = document.createElement("h3");
    heading.textContent = escapeText(item.topic);
    const meta = document.createElement("p");
    meta.className = "history-meta";
    const mode = MODE_LABELS[escapeText(item.source)] || "学习会话";
    meta.textContent = `${formatTime(item.created_at)} · ${mode}`;
    card.append(heading, meta);
    const goal = escapeText(item.learning_goal);
    if (goal) {
      const goalLine = document.createElement("p");
      goalLine.className = "history-goal";
      goalLine.textContent = goal;
      card.append(goalLine);
    }
    historyList.append(card);
  }
}

async function loadHistory() {
  const learner = learnerInput.value.trim() || "local-learner";
  historyError.textContent = "";
  historyList.replaceChildren();
  historyCount.textContent = "正在读取历史问题…";
  try {
    const response = await fetch(
      `/api/learners/${encodeURIComponent(learner)}/questions`,
      { headers: { Accept: "application/json" } },
    );
    if (!response.ok) {
      throw new Error(`查询失败（HTTP ${response.status}）`);
    }
    const data = await response.json();
    historyLearner.textContent = learner;
    historyCount.textContent = `共 ${data.questions.length} 条记录`;
    renderQuestions(data.questions);
  } catch (error) {
    historyCount.textContent = "读取历史问题失败";
    historyError.textContent = error?.message || String(error);
  }
}

refreshButton.addEventListener("click", loadHistory);
learnerInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadHistory();
});

loadHistory();
