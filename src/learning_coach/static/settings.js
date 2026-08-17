const apiForm = document.querySelector("#api-config-form");
const apiChatProvider = document.querySelector("#api-chat-provider");
const apiChatModel = document.querySelector("#api-chat-model");
const apiAssessmentProvider = document.querySelector("#api-assessment-provider");
const apiAssessmentModel = document.querySelector("#api-assessment-model");
const applyApiButton = document.querySelector("#apply-api-config");
const apiError = document.querySelector("#api-config-error");
const apiStatus = document.querySelector("#api-config-status");
const cliForm = document.querySelector("#cli-config-form");
const cliProvider = document.querySelector("#cli-provider");
const cliError = document.querySelector("#cli-config-error");
const cliStatus = document.querySelector("#cli-config-status");
const currentRuntime = document.querySelector("#current-runtime");
const keyInputs = {
  openai: document.querySelector("#openai-api-key"),
  anthropic: document.querySelector("#anthropic-api-key"),
  google_genai: document.querySelector("#google-genai-api-key"),
};

let testedConfigId = null;

function errorDetail(error) {
  const detail = error?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) return detail[0].msg;
  return "请求没有完成，请检查配置后重试。";
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw payload;
  return payload;
}

function jsonOptions(method, payload = {}) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

function modelId(provider, name) {
  const normalized = name.trim();
  if (!normalized) throw new Error("模型名称不能为空。");
  return `${provider}:${normalized}`;
}

function renderCurrent(config) {
  if (!config.configured) {
    currentRuntime.textContent = config.error;
    currentRuntime.classList.add("error");
    return;
  }
  currentRuntime.classList.remove("error");
  const mode = config.auth_mode === "cli" ? "官方 CLI" : "内存 API";
  const assessment = config.chat_model_id === config.assessment_model_id
    ? "主模型同时负责评价"
    : `评价 ${config.assessment_model_id}`;
  currentRuntime.textContent = `版本 ${config.version} · ${mode} · ${config.chat_model_id} · ${assessment}`;
}

function invalidateApiTest() {
  testedConfigId = null;
  applyApiButton.disabled = true;
  apiStatus.textContent = "配置发生变化，请重新测试连接。";
}

function setBusy(form, busy) {
  form.classList.toggle("loading", busy);
  form.querySelectorAll("button").forEach((button) => {
    button.disabled = busy || (button === applyApiButton && !testedConfigId);
  });
}

[
  apiChatProvider,
  apiChatModel,
  apiAssessmentProvider,
  apiAssessmentModel,
  ...Object.values(keyInputs),
].forEach((element) => element.addEventListener("input", invalidateApiTest));

apiForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  apiError.textContent = "";
  apiStatus.textContent = "";
  testedConfigId = null;
  setBusy(apiForm, true);
  try {
    const providers = new Set([apiChatProvider.value, apiAssessmentProvider.value]);
    const apiKeys = {};
    for (const provider of providers) {
      const value = keyInputs[provider].value.trim();
      if (!value) throw new Error(`请填写 ${provider} API Key。`);
      apiKeys[provider] = value;
    }
    const tested = await request(
      "/api/model-config/test",
      jsonOptions("POST", {
        chat_model_id: modelId(apiChatProvider.value, apiChatModel.value),
        assessment_model_id: modelId(apiAssessmentProvider.value, apiAssessmentModel.value),
        api_keys: apiKeys,
      }),
    );
    testedConfigId = tested.test_id;
    applyApiButton.disabled = false;
    apiStatus.textContent = `测试通过；票据有效至 ${new Date(tested.expires_at).toLocaleTimeString()}。`;
  } catch (error) {
    apiError.textContent = error.message || errorDetail(error);
  } finally {
    setBusy(apiForm, false);
  }
});

applyApiButton.addEventListener("click", async () => {
  if (!testedConfigId) return;
  apiError.textContent = "";
  setBusy(apiForm, true);
  try {
    const config = await request(
      "/api/model-config",
      jsonOptions("PUT", { auth_mode: "api", test_id: testedConfigId }),
    );
    testedConfigId = null;
    Object.values(keyInputs).forEach((input) => { input.value = ""; });
    renderCurrent(config);
    apiStatus.textContent = "配置已应用，只影响之后创建的新会话。";
  } catch (error) {
    apiError.textContent = errorDetail(error);
  } finally {
    setBusy(apiForm, false);
  }
});

function cliModelId() {
  return cliProvider.value === "codex" ? "codex_cli:default" : "claude_code:default";
}

async function runCliAuth(action) {
  cliError.textContent = "";
  cliStatus.textContent = "正在等待官方 CLI…";
  setBusy(cliForm, true);
  try {
    const url = `/api/model-auth/${cliProvider.value}/${action}`;
    const payload = action === "status"
      ? await request(url)
      : await request(url, jsonOptions("POST"));
    cliStatus.textContent = `${payload.provider} ${payload.action} 已完成。`;
  } catch (error) {
    cliStatus.textContent = "";
    cliError.textContent = errorDetail(error);
  } finally {
    setBusy(cliForm, false);
  }
}

document.querySelector("#cli-status").addEventListener("click", () => runCliAuth("status"));
document.querySelector("#cli-login").addEventListener("click", () => runCliAuth("login"));
document.querySelector("#cli-logout").addEventListener("click", () => runCliAuth("logout"));

cliForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  cliError.textContent = "";
  setBusy(cliForm, true);
  try {
    const selectedModel = cliModelId();
    const config = await request(
      "/api/model-config",
      jsonOptions("PUT", {
        auth_mode: "cli",
        chat_model_id: selectedModel,
        assessment_model_id: selectedModel,
      }),
    );
    renderCurrent(config);
    cliStatus.textContent = "CLI 模型已应用，只影响之后创建的新会话。";
  } catch (error) {
    cliError.textContent = errorDetail(error);
  } finally {
    setBusy(cliForm, false);
  }
});

request("/api/model-config")
  .then(renderCurrent)
  .catch((error) => {
    currentRuntime.textContent = errorDetail(error);
    currentRuntime.classList.add("error");
  });
