import assert from "node:assert/strict";
import test from "node:test";
import {
  AUTH_REQUIRED_EVENT,
  createAdminUser,
  deleteAdminUser,
  deleteNotificationSubscription,
  getPlatformSettings,
  getUserSettings,
  getWebSocketTicket,
  getCurrentUser,
  getVapidPublicKey,
  login,
  listAdminUsers,
  sendTestNotification,
  updateAdminUser,
  updatePlatformSettings,
  updateUserSettings,
  wsUrl,
} from "./api";
import {
  listNotificationSubscriptions,
  postNotificationSubscriptionPresence,
} from "./api";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

function setFetch(handler: typeof fetch): void {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: handler,
  });
}

test.afterEach(() => {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: originalFetch,
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    writable: true,
    value: originalWindow,
  });
});

function setWindowTarget(): EventTarget {
  const windowTarget = new EventTarget();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    writable: true,
    value: windowTarget,
  });
  return windowTarget;
}

test("getVapidPublicKey returns configured key", async () => {
  setFetch(
    async () =>
      new Response(JSON.stringify({ vapid_public_key: "test-public-key" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
  );

  const vapidPublicKey = await getVapidPublicKey(
    "https://carapace.example.test",
  );

  assert.equal(vapidPublicKey, "test-public-key");
});

test("getVapidPublicKey surfaces backend detail messages on failure", async () => {
  setFetch(
    async () =>
      new Response(
        JSON.stringify({ detail: "VAPID public key is not configured" }),
        {
          status: 404,
          headers: { "Content-Type": "application/json" },
        },
      ),
  );

  await assert.rejects(
    () => getVapidPublicKey("https://carapace.example.test"),
    /VAPID public key is not configured/,
  );
});

test("deleteNotificationSubscription ignores missing subscriptions", async () => {
  let called = 0;
  setFetch(async () => {
    called += 1;
    return new Response(null, { status: 404 });
  });

  await deleteNotificationSubscription(
    "https://carapace.example.test",
    "token-1",
    "sub-1",
  );

  assert.equal(called, 1);
});

test("listNotificationSubscriptions surfaces backend detail messages on failure", async () => {
  setFetch(
    async () =>
      new Response(
        JSON.stringify({ detail: "subscription store unavailable" }),
        {
          status: 503,
          headers: { "Content-Type": "application/json" },
        },
      ),
  );

  await assert.rejects(
    () =>
      listNotificationSubscriptions("https://carapace.example.test", "token-1"),
    /subscription store unavailable/,
  );
});

test("postNotificationSubscriptionPresence rejects failed heartbeats", async () => {
  setFetch(async () => new Response(null, { status: 500 }));

  await assert.rejects(
    () =>
      postNotificationSubscriptionPresence(
        "https://carapace.example.test",
        "token-1",
        "sub-1",
        {
          session_id: "session-1",
          client_type: "web",
          focus_state: "visible",
        },
      ),
    /Failed to update notification subscription presence: 500/,
  );
});

test("sendTestNotification surfaces backend detail messages on failure", async () => {
  setFetch(
    async () =>
      new Response(
        JSON.stringify({ detail: "Failed to deliver test notification" }),
        {
          status: 502,
          headers: { "Content-Type": "application/json" },
        },
      ),
  );

  await assert.rejects(
    () =>
      sendTestNotification("https://carapace.example.test", "token-1", "sub-1"),
    /Failed to deliver test notification/,
  );
});

test("getCurrentUser parses authenticated user roles", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    calls.push(new Request(input, init));
    return new Response(
      JSON.stringify({
        username: "admin",
        display_name: "Admin",
        roles: ["admin"],
        config: { agent_name: "Jarvis" },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  const user = await getCurrentUser("https://carapace.example.test");

  assert.equal(calls[0]?.url, "https://carapace.example.test/api/auth/me");
  assert.deepEqual(user.roles, ["admin"]);
  assert.equal(user.agentName, "Jarvis");
});

test("authenticated API 401 dispatches auth-required event", async () => {
  const windowTarget = setWindowTarget();
  let authRequiredEvents = 0;
  windowTarget.addEventListener(AUTH_REQUIRED_EVENT, () => {
    authRequiredEvents += 1;
  });
  setFetch(
    async () =>
      new Response(JSON.stringify({ detail: "Invalid session" }), {
        status: 401,
      }),
  );

  await assert.rejects(
    () => getCurrentUser("https://carapace.example.test"),
    /Invalid session/,
  );

  assert.equal(authRequiredEvents, 1);
});

test("login 401 does not dispatch auth-required event", async () => {
  const windowTarget = setWindowTarget();
  let authRequiredEvents = 0;
  windowTarget.addEventListener(AUTH_REQUIRED_EVENT, () => {
    authRequiredEvents += 1;
  });
  setFetch(
    async () =>
      new Response(JSON.stringify({ detail: "Invalid username or password" }), {
        status: 401,
      }),
  );

  await assert.rejects(
    () => login("https://carapace.example.test", "thies", "wrong"),
    /Invalid username or password/,
  );

  assert.equal(authRequiredEvents, 0);
});

test("admin user helpers use cookie auth and parse users", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    calls.push(request);
    return new Response(
      JSON.stringify([
        {
          username: "thies",
          enabled: true,
          token_version: 2,
          display_name: "Thies",
          email: "thies@example.test",
          roles: ["admin"],
          created_at: "2026-05-24T12:00:00Z",
          updated_at: "2026-05-24T12:00:00Z",
          password_changed_at: "2026-05-24T12:00:00Z",
          last_login_at: null,
          config: {},
        },
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  const users = await listAdminUsers("https://carapace.example.test");

  assert.equal(calls[0].headers.get("Authorization"), null);
  assert.equal(users[0].username, "thies");
  assert.equal(users[0].roles[0], "admin");
});

test("getWebSocketTicket posts with cookie credentials", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    calls.push(new Request(input, init));
    return new Response(JSON.stringify({ ticket: "ws-ticket-1" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });

  const ticket = await getWebSocketTicket("https://carapace.example.test", "");

  assert.equal(ticket, "ws-ticket-1");
  assert.equal(calls[0]?.method, "POST");
  assert.equal(calls[0]?.credentials, "include");
  assert.equal(
    calls[0]?.url,
    "https://carapace.example.test/api/auth/ws-ticket",
  );
});

test("wsUrl includes client id and websocket ticket", () => {
  assert.equal(
    wsUrl(
      "https://carapace.example.test",
      "session-1",
      "",
      "web tab",
      "ticket.1",
    ),
    "wss://carapace.example.test/api/chat/session-1?client_id=web+tab&ticket=ticket.1",
  );
});

test("createAdminUser posts admin payload", async () => {
  let capturedBody = "";
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    capturedBody = await request.text();
    return new Response(
      JSON.stringify({
        username: "ada",
        enabled: true,
        token_version: 1,
        display_name: "Ada",
        email: null,
        roles: [],
        created_at: "2026-05-24T12:00:00Z",
        updated_at: "2026-05-24T12:00:00Z",
        password_changed_at: "2026-05-24T12:00:00Z",
        last_login_at: null,
        config: {},
      }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    );
  });

  const user = await createAdminUser("https://carapace.example.test", {
    username: "ada",
    password: "secret",
    display_name: "Ada",
  });

  assert.equal(JSON.parse(capturedBody).username, "ada");
  assert.equal(user.username, "ada");
});

test("updateAdminUser encodes username and surfaces backend errors", async () => {
  let capturedUrl = "";
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    capturedUrl = request.url;
    return new Response(JSON.stringify({ detail: "User not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  });

  await assert.rejects(
    () =>
      updateAdminUser("https://carapace.example.test", "ada lovelace", {
        enabled: false,
      }),
    /User not found/,
  );
  assert.equal(
    capturedUrl,
    "https://carapace.example.test/api/admin/users/ada%20lovelace",
  );
});

test("deleteAdminUser deletes the selected user", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    calls.push(new Request(input, init));
    return new Response(null, { status: 204 });
  });

  await deleteAdminUser("https://carapace.example.test", "ada lovelace");

  assert.equal(calls[0]?.method, "DELETE");
  assert.equal(
    calls[0]?.url,
    "https://carapace.example.test/api/admin/users/ada%20lovelace",
  );
  assert.equal(calls[0]?.headers.get("Authorization"), null);
});

test("user settings helpers decode write-only status and patch payloads", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    calls.push(request);
    return new Response(
      JSON.stringify({
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
          default_models: { agent: "anthropic:default" },
          default_budget: { tool_calls: 3, cost_usd: "1.50" },
          timezone: "Europe/Berlin",
          memory: { auto_mode: true, budget: { cost_usd_per_day: "1.00", cost_usd_per_month: null, input_tokens_per_day: 50000, input_tokens_per_month: null } },
          matrix: {
            enabled: true,
            homeserver: "https://matrix.example.test",
            user_id: "@bot:example.test",
            device_name: "carapace",
            password_set: true,
            token_set: true,
            allowed_rooms: [],
            allowed_users: ["@thies:example.test"],
          },
          credentials: {
            backends: {
              vault: {
                type: "bitwarden",
                url: "http://carapace-bitwarden:8087",
                basic_auth: { username: "thies", password_set: true },
                expose: [],
                hide: [],
              },
            },
          },
          git: {
            remote: "https://git.example.test/repo.git",
            branch: "main",
            author: "carapace",
            token_set: true,
          },
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  const settings = await getUserSettings("https://carapace.example.test", "");
  const patched = await updateUserSettings(
    "https://carapace.example.test",
    "",
    {
      default_budget: { tool_calls: 4 },
      git: { clear_token: true },
    },
  );

  assert.equal(settings.settings.matrix.password_set, true);
  assert.equal(settings.settings.timezone, "Europe/Berlin");
  assert.deepEqual(settings.settings.memory, {
    auto_mode: true,
    budget: { cost_usd_per_day: "1.00", cost_usd_per_month: null, input_tokens_per_day: 50000, input_tokens_per_month: null },
  });
  assert.equal(settings.settings.credentials.backends.vault?.type, "bitwarden");
  assert.equal(patched.settings.git.token_set, true);
  assert.equal(
    calls[0]?.url,
    "https://carapace.example.test/api/user/settings",
  );
  assert.equal(calls[1]?.method, "PATCH");
  assert.deepEqual(JSON.parse(await calls[1]!.text()).git, {
    clear_token: true,
  });
});

test("platform settings helpers parse model secrets and send patches", async () => {
  const calls: Request[] = [];
  setFetch(async (input, init) => {
    const request = new Request(input, init);
    calls.push(request);
    return new Response(
      JSON.stringify({
        config_path: "/var/lib/carapace-config/config.yaml",
        config_writable: true,
        settings: {
          default_models: {
            agent: "local:test",
            sentinel: "local:test-low",
            title: "anthropic:claude-haiku-4-5",
          },
          default_budget: { cost_usd: "2.50" },
          available_models: [
            {
              id: "local:test",
              provider: "openai",
              name: "gpt-4o-mini",
              base_url: "http://127.0.0.1:1234/v1",
              thinking_budget_tokens: 128,
              api_key: {
                source: "env",
                value: "LOCAL_API_KEY",
                configured: true,
              },
            },
            {
              id: "anthropic:claude-haiku-4-5",
              provider: "anthropic",
              name: "claude-haiku-4-5",
              api_key: { source: "raw", configured: true },
            },
          ],
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  const settings = await getPlatformSettings(
    "https://carapace.example.test",
    "",
  );
  const patched = await updatePlatformSettings(
    "https://carapace.example.test",
    "",
    {
      default_models: settings.settings.default_models,
      default_budget: { cost_usd: "2.50" },
      compaction: {
        keep_turns: 6,
        verbatim_tool_turns: 2,
        tool_output_floor_tokens: 500,
      },
      available_models: [
        {
          provider: "openai",
          name: "gpt-4o-mini",
          id: "local:test",
          base_url: "http://127.0.0.1:1234/v1",
          api_key: { source: "env", value: "LOCAL_API_KEY" },
        },
      ],
    },
  );

  assert.equal(settings.config_writable, true);
  assert.equal(
    settings.settings.available_models[0]?.api_key.value,
    "LOCAL_API_KEY",
  );
  assert.equal(settings.settings.available_models[1]?.api_key.source, "raw");
  assert.equal(patched.settings.default_models.agent, "local:test");
  assert.equal(
    calls[0]?.url,
    "https://carapace.example.test/api/admin/platform/settings",
  );
  assert.equal(calls[1]?.method, "PATCH");
  assert.deepEqual(
    JSON.parse(await calls[1]!.text()).available_models[0].api_key,
    {
      source: "env",
      value: "LOCAL_API_KEY",
    },
  );
});
