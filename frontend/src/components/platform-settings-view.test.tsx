import assert from "node:assert/strict";
import test from "node:test";

import { flushReact, installDom, renderReact, runInAct } from "../../test/react-test-utils";

import { buildPlatformSettingsPatch, ModelRow, sortModelDrafts } from "./platform-settings-view";

type PlatformDraft = Parameters<typeof buildPlatformSettingsPatch>[0];

function translate(key: string, values?: Record<string, string | number>): string {
  if (!values) return key;
  return Object.entries(values).reduce((message, [name, value]) => message.replaceAll(`{${name}}`, String(value)), key);
}

function draftWithModel(model: PlatformDraft["models"][number]): PlatformDraft {
  const id = model.id || `${model.provider}:${model.name}`;
  return {
    defaultModels: {
      agent: id,
      sentinel: id,
      title: id,
      compaction: "",
      memory_low: null,
      memory_high: null,
    },
    budget: {
      input_tokens: "",
      output_tokens: "",
      cost_usd: "",
      tool_calls: "",
    },
    compaction: {
      keepTurns: "6",
      verbatimTurns: "2",
      toolFloor: "500",
    },
    models: [model],
  };
}

test("buildPlatformSettingsPatch keeps default models the view does not edit", () => {
  const draft = draftWithModel({
    rowId: "model-1",
    provider: "anthropic",
    name: "claude-haiku-4-5",
    id: "",
    maxInputTokens: "",
    thinking: "",
    thinkingBudgetTokens: "",
    baseUrl: "",
    vision: false,
    enabled: true,
    apiKeySource: "none",
    apiKeyValue: "",
    apiKeyConfigured: false,
    apiKeyConfiguredSource: "none",
  });
  draft.defaultModels.memory_low = "anthropic:claude-haiku-4-5";

  const patch = buildPlatformSettingsPatch(draft, translate);

  assert.equal(patch.default_models.memory_low, "anthropic:claude-haiku-4-5");
  assert.equal(patch.default_models.memory_high, null);
});

test("buildPlatformSettingsPatch omits OpenAI-only fields for other providers", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "anthropic",
      name: "claude-haiku-4-5",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "128",
      baseUrl: "http://127.0.0.1:1234/v1",
      vision: false,
      enabled: true,
      apiKeySource: "raw",
      apiKeyValue: "",
      apiKeyConfigured: true,
      apiKeyConfiguredSource: "raw",
    }),
    translate,
  );

  const model = patch.available_models[0]!;
  assert.equal(model.provider, "anthropic");
  assert.equal(Object.hasOwn(model, "thinking_budget_tokens"), false);
  assert.equal(Object.hasOwn(model, "base_url"), false);
  assert.equal(Object.hasOwn(model, "api_key"), false);
});

test("buildPlatformSettingsPatch reuses configured raw OpenAI secrets", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "openai",
      name: "gpt-4o-mini",
      id: "local:test",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "http://127.0.0.1:1234/v1",
      vision: false,
      enabled: true,
      apiKeySource: "raw",
      apiKeyValue: "",
      apiKeyConfigured: true,
      apiKeyConfiguredSource: "raw",
    }),
    translate,
  );

  assert.deepEqual(patch.available_models[0]?.api_key, { source: "raw" });
});

test("buildPlatformSettingsPatch includes OpenRouter API key fields without base URL", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "openrouter",
      name: "anthropic/claude-sonnet-4.5",
      id: "openrouter:sonnet",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "128",
      baseUrl: "https://openrouter.ai/api/v1",
      vision: false,
      enabled: true,
      apiKeySource: "env",
      apiKeyValue: "OPENROUTER_API_KEY",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    }),
    translate,
  );

  const model = patch.available_models[0]!;
  assert.equal(model.provider, "openrouter");
  assert.deepEqual(model.api_key, { source: "env", value: "OPENROUTER_API_KEY" });
  assert.equal(Object.hasOwn(model, "base_url"), false);
  assert.equal(Object.hasOwn(model, "thinking_budget_tokens"), false);
});

test("buildPlatformSettingsPatch carries the vision flag", () => {
  const patch = buildPlatformSettingsPatch(
    draftWithModel({
      rowId: "model-1",
      provider: "anthropic",
      name: "claude-sonnet-4-6",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "",
      vision: true,
      enabled: true,
      apiKeySource: "none",
      apiKeyValue: "",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    }),
    translate,
  );

  assert.equal(patch.available_models[0]?.vision, true);
});

test("sortModelDrafts orders complete rows by provider then model name while keeping incomplete rows first", () => {
  const sorted = sortModelDrafts([
    {
      rowId: "model-1",
      provider: "openai",
      name: "gpt-4o-mini",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "",
      vision: false,
      enabled: true,
      apiKeySource: "none",
      apiKeyValue: "",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    },
    {
      rowId: "model-2",
      provider: "anthropic",
      name: "claude-sonnet-4-6",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "",
      vision: false,
      enabled: true,
      apiKeySource: "none",
      apiKeyValue: "",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    },
    {
      rowId: "model-3",
      provider: "openai",
      name: "",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "",
      vision: false,
      enabled: true,
      apiKeySource: "none",
      apiKeyValue: "",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    },
    {
      rowId: "model-4",
      provider: "anthropic",
      name: "claude-haiku-4-5",
      id: "",
      maxInputTokens: "",
      thinking: "",
      thinkingBudgetTokens: "",
      baseUrl: "",
      vision: false,
      enabled: true,
      apiKeySource: "none",
      apiKeyValue: "",
      apiKeyConfigured: false,
      apiKeyConfiguredSource: "none",
    },
  ]);

  assert.deepEqual(
    sorted.map((model) => model.rowId),
    ["model-3", "model-4", "model-2", "model-1"],
  );
});

test("ModelRow reopens incomplete rows after a manual collapse", async () => {
  const cleanup = installDom();

  try {
    const view = await renderReact(
      <ModelRow
        model={{
          rowId: "model-1",
          provider: "openai",
          name: "",
          id: "",
          maxInputTokens: "",
          thinking: "",
          thinkingBudgetTokens: "",
          baseUrl: "",
          vision: false,
          enabled: true,
          apiKeySource: "none",
          apiKeyValue: "",
          apiKeyConfigured: false,
          apiKeyConfiguredSource: "none",
        }}
        disabled={false}
        onChange={() => undefined}
        onRemove={() => undefined}
        onCopy={() => undefined}
        t={translate}
      />,
    );

    try {
      const details = view.container.querySelector("details");
      assert.ok(details instanceof HTMLElement);
      assert.equal((details as HTMLDetailsElement).open, true);

      await runInAct(() => {
        (details as HTMLDetailsElement).open = false;
        details.dispatchEvent(new window.Event("toggle", { bubbles: true }));
      });
      await flushReact();

      assert.equal((details as HTMLDetailsElement).open, true);
    } finally {
      await view.unmount();
    }
  } finally {
    cleanup();
  }
});
