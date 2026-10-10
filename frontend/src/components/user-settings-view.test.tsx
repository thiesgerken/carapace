import assert from "node:assert/strict";
import test from "node:test";

import type { UserSettingsResponseInfo } from "@/lib/api";
import { buildUserSettingsPatch } from "./user-settings-view";

function userSettingsResponse(defaultBudget: { tool_calls: number }): UserSettingsResponseInfo {
  return {
    capabilities: {
      file_credential_backend: false,
    },
    server_defaults: {
      models: {
        agent: "anthropic:default",
        sentinel: "anthropic:guard",
        title: "anthropic:title",
      },
      budget: {},
    },
    available_models: [
      { id: "anthropic:default", provider: "anthropic", name: "default" },
    ],
    settings: {
      agent_name: "",
      agent_icon: "",
      default_models: { agent: "anthropic:default" },
      default_budget: defaultBudget,
      matrix: {
        enabled: false,
        homeserver: "",
        user_id: "",
        device_name: "carapace",
        password_set: false,
        token_set: false,
        allowed_rooms: [],
        allowed_users: [],
      },
      credentials: {
        backends: {
          dev: {
            type: "file",
            path: "secrets.env",
            expose: ["API_TOKEN"],
            hide: [],
          },
        },
      },
      git: {
        remote: "",
        branch: "main",
        author: "carapace <carapace@%h>",
        token_set: false,
      },
    },
  };
}

test("buildUserSettingsPatch omits unchanged credentials when file backends are unsupported", () => {
  const settings = userSettingsResponse({ tool_calls: 3 });
  const draft: Parameters<typeof buildUserSettingsPatch>[0] = {
    agentName: "",
    agentIcon: "",
    defaultModels: settings.settings.default_models,
    budget: {
      input_tokens: "",
      output_tokens: "",
      cost_usd: "",
      tool_calls: "4",
    },
    matrix: settings.settings.matrix,
    matrixPassword: "",
    credentials: [
      {
        id: "credential-backend-1",
        name: "dev",
        type: "file",
        path: "secrets.env",
        url: "http://127.0.0.1:8087",
        expose: "API_TOKEN",
        hide: "",
        basicAuthEnabled: false,
        basicAuthUsername: "",
        basicAuthPassword: "",
        basicAuthPasswordSet: false,
      },
    ],
    git: settings.settings.git,
    gitToken: "",
  };

  const patch = buildUserSettingsPatch(draft, settings, (key) => key);

  assert.equal(patch.default_budget?.tool_calls, 4);
  assert.equal(Object.hasOwn(patch, "credentials"), false);
});

test("buildUserSettingsPatch keeps default models the view does not edit", () => {
  const settings = userSettingsResponse({ tool_calls: 3 });
  settings.settings.default_models = {
    agent: "anthropic:default",
    compaction: "anthropic:title",
    memory_low: "anthropic:title",
  };
  const draft: Parameters<typeof buildUserSettingsPatch>[0] = {
    agentName: "",
    agentIcon: "",
    defaultModels: settings.settings.default_models,
    budget: { input_tokens: "", output_tokens: "", cost_usd: "", tool_calls: "3" },
    matrix: settings.settings.matrix,
    matrixPassword: "",
    credentials: [],
    git: settings.settings.git,
    gitToken: "",
  };

  const patch = buildUserSettingsPatch(draft, settings, (key) => key);

  assert.equal(patch.default_models?.compaction, "anthropic:title");
  assert.equal(patch.default_models?.memory_low, "anthropic:title");
});
