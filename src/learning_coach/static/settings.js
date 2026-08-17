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
const currentRuntimeModel = document.querySelector("#current-runtime-model");
const currentRuntimeDetail = document.querySelector("#current-runtime-detail");
const providerCredentials = document.querySelector("#provider-credentials");

const PROVIDER_PRESETS = Object.freeze({
  openai: {
    label: "OpenAI",
    defaultModel: "gpt-5-mini",
    baseUrl: null,
  },
  anthropic: {
    label: "Anthropic",
    defaultModel: "claude-sonnet-4-6",
    baseUrl: null,
  },
  google_genai: {
    label: "Google GenAI",
    defaultModel: "gemini-2.5-flash-lite",
    baseUrl: null,
  },
  deepseek: {
    label: "DeepSeek",
    defaultModel: "deepseek-v4-flash",
    baseUrl: "https://api.deepseek.com",
  },
  dashscope: {
    label: "通义千问 · 阿里云百炼",
    defaultModel: "qwen-plus",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  zhipu: {
    label: "智谱 GLM",
    defaultModel: "glm-5-turbo",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
  },
  openai_compatible: {
    label: "自定义 OpenAI 兼容接口",
    defaultModel: "",
    baseUrl: "",
  },
});

const credentialDrafts = new Map();

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

function makeCredentialField({ id, label, type, value, placeholder, field }) {
  const wrapper = document.createElement("label");
  wrapper.htmlFor = id;
  wrapper.textContent = label;
  const input = document.createElement("input");
  input.id = id;
  input.type = type;
  input.value = value;
  input.placeholder = placeholder;
  input.autocomplete = "off";
  input.dataset.field = field;
  input.addEventListener("input", invalidateApiTest);
  wrapper.append(input);
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
      card.append(makeCredentialField({
        id: `${provider}-base-url`,
        label: `${preset.label} Base URL · 仅支持 HTTPS`,
        type: "url",
        value: draft.baseUrl,
        placeholder: "https://api.example.com/v1",
        field: "base-url",
      }));
    }
    providerCredentials.append(card);
  });
}

function useProviderPreset(providerSelect, modelInput) {
  const preset = PROVIDER_PRESETS[providerSelect.value];
  modelInput.value = preset.defaultModel;
  renderProviderCredentials();
  invalidateApiTest();
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

function invalidateApiTest() {
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
  useProviderPreset(apiChatProvider, apiChatModel);
});
apiAssessmentProvider.addEventListener("change", () => {
  useProviderPreset(apiAssessmentProvider, apiAssessmentModel);
});
[apiChatModel, apiAssessmentModel].forEach((element) => {
  element.addEventListener("input", invalidateApiTest);
});

apiForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  apiError.textContent = "";
  apiStatus.textContent = "";
  testedConfigId = null;
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
    currentRuntimeModel.textContent = "无法读取当前模型";
    currentRuntimeDetail.textContent = errorDetail(error);
    currentRuntime.classList.add("error");
  });

renderProviderCredentials({ preserve: false });
