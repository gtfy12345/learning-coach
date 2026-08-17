const apiForm = document.querySelector("#api-config-form");
const apiChatProvider = document.querySelector("#api-chat-provider");
const apiChatModel = document.querySelector("#api-chat-model");
const apiAssessmentProvider = document.querySelector("#api-assessment-provider");
const apiAssessmentModel = document.querySelector("#api-assessment-model");
const chatSuggestions = document.querySelector("#chat-model-suggestions");
const assessmentSuggestions = document.querySelector("#assessment-model-suggestions");
const applyApiButton = document.querySelector("#apply-api-config");
const testApiButton = document.querySelector("#test-api-config");
const apiError = document.querySelector("#api-config-error");
const apiStatus = document.querySelector("#api-config-status");
const cliForm = document.querySelector("#cli-config-form");
const cliProvider = document.querySelector("#cli-provider");
const cliError = document.querySelector("#cli-config-error");
const cliStatus = document.querySelector("#cli-config-status");
const currentRuntime = document.querySelector("#current-runtime");
const currentRuntimeModel = document.querySelector("#current-runtime-model");
const currentRuntimeDetail = document.querySelector("#current-runtime-detail");
const providerCredentials = document.querySelector("#provider-credentials");
const providerShowcaseButtons = document.querySelectorAll(
  ".provider-showcase button[data-provider]",
);

const PROVIDER_PRESETS = Object.freeze({
  openai: {
    label: "OpenAI",
    defaultModel: "gpt-5-mini",
    baseUrl: null,
    suggestions: ["gpt-5-mini", "gpt-5", "gpt-5.4"],
  },
  anthropic: {
    label: "Anthropic",
    defaultModel: "claude-sonnet-4-6",
    baseUrl: null,
    suggestions: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
  },
  google_genai: {
    label: "Google GenAI",
    defaultModel: "gemini-2.5-flash-lite",
    baseUrl: null,
    suggestions: ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"],
  },
  deepseek: {
    label: "DeepSeek",
    defaultModel: "deepseek-v4-flash",
    baseUrl: "https://api.deepseek.com",
    suggestions: ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
  },
  dashscope: {
    label: "通义千问 · 阿里云百炼",
    defaultModel: "qwen-plus",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    suggestions: ["qwen-plus", "qwen-max", "qwen-turbo"],
  },
  zhipu: {
    label: "智谱 GLM",
    defaultModel: "glm-5-turbo",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    suggestions: ["glm-5-turbo", "glm-5"],
  },
  openai_compatible: {
    label: "自定义 OpenAI 兼容接口",
    defaultModel: "",
    baseUrl: "",
    suggestions: [],
  },
});

const CLI_LABELS = { codex: "Codex CLI", claude: "Claude Code" };

const credentialDrafts = new Map();
const modelDrafts = new Map();
let lastChatProvider = apiChatProvider.value;
let lastAssessmentProvider = apiAssessmentProvider.value;
let testedConfigId = null;
let ticketTimer = null;

function selectedProviders() {
  return [...new Set([apiChatProvider.value, apiAssessmentProvider.value])];
}

function captureProviderCredentials() {
  providerCredentials.querySelectorAll(".provider-credential").forEach((card) => {
    const provider = card.dataset.provider;
    credentialDrafts.set(provider, {
      apiKey: card.querySelector('[data-field="api-key"]').value,
      baseUrl: card.querySelector('[data-field="base-url"]')?.value || "",
    });
  });
}

function rememberModelName(provider, name) {
  const normalized = (name || "").trim();
  if (provider && normalized) modelDrafts.set(provider, normalized);
}

function refreshModelSuggestions(datalist, preset) {
  datalist.replaceChildren(
    ...(preset.suggestions || []).map((model) => {
      const option = document.createElement("option");
      option.value = model;
      return option;
    }),
  );
}

function isHttpsBaseUrl(value) {
  return /^https:\/\//.test(value);
}

function validateBaseUrl(input, hint) {
  const value = (input.value || "").trim();
  const invalid = value !== "" && !isHttpsBaseUrl(value);
  input.setAttribute("aria-invalid", String(invalid));
  if (hint) hint.textContent = invalid ? "Base URL 仅支持 HTTPS，必须以 https:// 开头。" : "";
  return !invalid;
}

function makeVisibilityToggle(input) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "visibility-toggle";
  button.dataset.action = "toggle-visibility";
  button.setAttribute("aria-pressed", "false");
  button.textContent = "显示";
  button.addEventListener("click", () => {
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.setAttribute("aria-pressed", String(reveal));
    button.textContent = reveal ? "隐藏" : "显示";
  });
  return button;
}

function makeCredentialField({ id, label, type, value, placeholder, field, hint = false }) {
  const wrapper = document.createElement("div");
  wrapper.className = "credential-field";
  const labelElement = document.createElement("label");
  labelElement.htmlFor = id;
  labelElement.textContent = label;
  wrapper.append(labelElement);

  const inputRow = document.createElement("div");
  inputRow.className = "credential-input-row";
  const input = document.createElement("input");
  input.id = id;
  input.type = type;
  input.value = value;
  input.placeholder = placeholder;
  input.autocomplete = "off";
  input.dataset.field = field;
  input.addEventListener("input", invalidateApiTest);
  inputRow.append(input);
  if (field === "api-key") inputRow.append(makeVisibilityToggle(input));
  wrapper.append(inputRow);

  if (hint) {
    const hintElement = document.createElement("small");
    hintElement.className = "field-hint";
    hintElement.dataset.hint = field;
    input.addEventListener("input", () => validateBaseUrl(input, hintElement));
    wrapper.append(hintElement);
  }
  return wrapper;
}

function renderProviderCredentials({ preserve = true } = {}) {
  if (preserve) captureProviderCredentials();
  providerCredentials.replaceChildren();

  selectedProviders().forEach((provider) => {
    const preset = PROVIDER_PRESETS[provider];
    const draft = credentialDrafts.get(provider) || {
      apiKey: "",
      baseUrl: preset.baseUrl || "",
    };
    const card = document.createElement("article");
    card.className = "provider-credential";
    card.classList.toggle("single-field", preset.baseUrl === null);
    card.dataset.provider = provider;

    const heading = document.createElement("div");
    heading.className = "provider-credential-heading";
    const title = document.createElement("strong");
    title.textContent = preset.label;
    const protocol = document.createElement("span");
    protocol.textContent = preset.baseUrl === null ? "原生 SDK" : "OpenAI 兼容";
    heading.append(title, protocol);
    card.append(heading);

    card.append(makeCredentialField({
      id: `${provider}-api-key`,
      label: `${preset.label} API Key`,
      type: "password",
      value: draft.apiKey,
      placeholder: "只保存在当前服务内存",
      field: "api-key",
    }));

    if (preset.baseUrl !== null) {
      const baseUrlField = makeCredentialField({
        id: `${provider}-base-url`,
        label: `${preset.label} Base URL · 仅支持 HTTPS`,
        type: "url",
        value: draft.baseUrl,
        placeholder: "https://api.example.com/v1",
        field: "base-url",
        hint: true,
      });
      validateBaseUrl(
        baseUrlField.querySelector('[data-field="base-url"]'),
        baseUrlField.querySelector('[data-hint="base-url"]'),
      );
      card.append(baseUrlField);
    }
    providerCredentials.append(card);
  });
}

function applyProviderPreset(providerSelect, modelInput, datalist) {
  const preset = PROVIDER_PRESETS[providerSelect.value];
  modelInput.value = modelDrafts.get(providerSelect.value) || preset.defaultModel;
  refreshModelSuggestions(datalist, preset);
  renderProviderCredentials();
  invalidateApiTest();
}

function syncProviderShowcase() {
  providerShowcaseButtons.forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.provider === apiChatProvider.value),
    );
  });
}

function selectChatProvider(provider) {
  if (!PROVIDER_PRESETS[provider]) return;
  if (apiChatProvider.value !== provider) {
    rememberModelName(lastChatProvider, apiChatModel.value);
    lastChatProvider = provider;
    apiChatProvider.value = provider;
    applyProviderPreset(apiChatProvider, apiChatModel, chatSuggestions);
    syncProviderShowcase();
  }
  apiChatModel.focus();
}

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
    currentRuntimeModel.textContent = "尚未配置可用模型";
    currentRuntimeDetail.textContent = config.error;
    currentRuntime.classList.add("error");
    return;
  }
  currentRuntime.classList.remove("error");
  const mode = config.auth_mode === "cli" ? "官方 CLI" : "内存 API";
  const assessment = config.chat_model_id === config.assessment_model_id
    ? "主模型同时负责评价"
    : `评价 ${config.assessment_model_id}`;
  currentRuntimeModel.textContent = config.chat_model_id;
  currentRuntimeDetail.textContent = `版本 ${config.version} · ${mode} · ${assessment}`;
}

function clearTicketCountdown() {
  if (ticketTimer !== null) {
    clearInterval(ticketTimer);
    ticketTimer = null;
  }
}

function formatCountdown(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function startTicketCountdown(expiresAt) {
  clearTicketCountdown();
  const deadline = new Date(expiresAt).getTime();
  const update = () => {
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      clearTicketCountdown();
      testedConfigId = null;
      applyApiButton.disabled = true;
      apiStatus.textContent = "测试票据已过期，请重新测试连接。";
      return;
    }
    apiStatus.textContent = `测试通过；票据 ${formatCountdown(remaining)} 后过期，过期前可应用配置。`;
  };
  update();
  ticketTimer = setInterval(update, 1000);
}

function invalidateApiTest() {
  clearTicketCountdown();
  testedConfigId = null;
  applyApiButton.disabled = true;
  apiStatus.textContent = "配置发生变化，请重新测试连接。";
}

function setBusy(form, busy) {
  form.classList.toggle("loading", busy);
  form.setAttribute("aria-busy", String(busy));
  form.querySelectorAll("button").forEach((button) => {
    button.disabled = busy || (button === applyApiButton && !testedConfigId);
  });
}

apiChatProvider.addEventListener("change", () => {
  rememberModelName(lastChatProvider, apiChatModel.value);
  lastChatProvider = apiChatProvider.value;
  applyProviderPreset(apiChatProvider, apiChatModel, chatSuggestions);
  syncProviderShowcase();
});
apiAssessmentProvider.addEventListener("change", () => {
  rememberModelName(lastAssessmentProvider, apiAssessmentModel.value);
  lastAssessmentProvider = apiAssessmentProvider.value;
  applyProviderPreset(apiAssessmentProvider, apiAssessmentModel, assessmentSuggestions);
});
providerShowcaseButtons.forEach((button) => {
  button.addEventListener("click", () => selectChatProvider(button.dataset.provider));
});
[apiChatModel, apiAssessmentModel].forEach((element) => {
  element.addEventListener("input", invalidateApiTest);
});

apiForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  apiError.textContent = "";
  apiStatus.textContent = "";
  clearTicketCountdown();
  testedConfigId = null;
  testApiButton.textContent = "测试中…";
  setBusy(apiForm, true);
  try {
    captureProviderCredentials();
    const providers = new Set(selectedProviders());
    const apiKeys = {};
    const baseUrls = {};
    for (const provider of providers) {
      const preset = PROVIDER_PRESETS[provider];
      const draft = credentialDrafts.get(provider) || {};
      const value = (draft.apiKey || "").trim();
      if (!value) throw new Error(`请填写 ${provider} API Key。`);
      apiKeys[provider] = value;
      if (preset.baseUrl !== null) {
        const baseUrl = (draft.baseUrl || "").trim();
        if (!baseUrl) throw new Error(`请填写 ${preset.label} Base URL。`);
        if (!isHttpsBaseUrl(baseUrl)) {
          throw new Error(`${preset.label} Base URL 仅支持 HTTPS，必须以 https:// 开头。`);
        }
        baseUrls[provider] = baseUrl;
      }
    }
    const tested = await request(
      "/api/model-config/test",
      jsonOptions("POST", {
        chat_model_id: modelId(apiChatProvider.value, apiChatModel.value),
        assessment_model_id: modelId(apiAssessmentProvider.value, apiAssessmentModel.value),
        api_keys: apiKeys,
        base_urls: baseUrls,
      }),
    );
    testedConfigId = tested.test_id;
    applyApiButton.disabled = false;
    startTicketCountdown(tested.expires_at);
  } catch (error) {
    apiError.textContent = error.message || errorDetail(error);
  } finally {
    testApiButton.textContent = "测试连接";
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
    clearTicketCountdown();
    testedConfigId = null;
    credentialDrafts.forEach((draft, provider) => {
      credentialDrafts.set(provider, { ...draft, apiKey: "" });
    });
    renderProviderCredentials({ preserve: false });
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

const CLI_ACTION_COPY = {
  status: "状态检查完成；登录详情输出在服务控制台。",
  login: "登录流程已完成。",
  logout: "已退出登录。",
};

async function runCliAuth(action) {
  cliError.textContent = "";
  cliStatus.textContent = "正在等待官方 CLI…";
  setBusy(cliForm, true);
  try {
    const url = `/api/model-auth/${cliProvider.value}/${action}`;
    const payload = action === "status"
      ? await request(url)
      : await request(url, jsonOptions("POST"));
    const label = CLI_LABELS[payload.provider] || payload.provider;
    cliStatus.textContent = `${label} ${CLI_ACTION_COPY[payload.action] || "操作已完成。"}`;
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
    currentRuntimeModel.textContent = "无法读取当前模型";
    currentRuntimeDetail.textContent = errorDetail(error);
    currentRuntime.classList.add("error");
  });

renderProviderCredentials({ preserve: false });
refreshModelSuggestions(chatSuggestions, PROVIDER_PRESETS[apiChatProvider.value]);
refreshModelSuggestions(assessmentSuggestions, PROVIDER_PRESETS[apiAssessmentProvider.value]);
syncProviderShowcase();
