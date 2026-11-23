import assert from "node:assert/strict";
import test from "node:test";
import { NextIntlClientProvider } from "next-intl";

import english from "../../messages/en.json";
import { installDom, renderReact } from "../../test/react-test-utils";
import type { CredentialApprovalRequest } from "@/lib/types";
import { CredentialApprovalCard } from "./credential-approval-card";

function request(overrides: Partial<CredentialApprovalRequest>): CredentialApprovalRequest {
  return {
    type: "credential_approval_request",
    request_id: "r1",
    vault_paths: [],
    names: [],
    descriptions: [],
    domains: [],
    explanation: "",
    ...overrides,
  };
}

async function renderText(req: CredentialApprovalRequest): Promise<string> {
  const view = await renderReact(
    <NextIntlClientProvider locale="en" messages={english} timeZone="UTC">
      <CredentialApprovalCard request={req} onRespond={() => {}} />
    </NextIntlClientProvider>,
  );
  const text = view.container.textContent ?? "";
  await view.unmount();
  return text;
}

test("a credential request keeps its title and shows no domain section", async () => {
  const restore = installDom();
  try {
    const text = await renderText(
      request({ vault_paths: ["demo/api-key"], names: ["Example API"], descriptions: ["read-only"] }),
    );
    assert.match(text, /Credential Request/);
    assert.doesNotMatch(text, /Domains:|Credentials:/);
  } finally {
    restore();
  }
});

test("an up-front request with domains only is an access request without a credentials label", async () => {
  const restore = installDom();
  try {
    const text = await renderText(request({ domains: ["uploads.example.net"] }));
    assert.match(text, /Access Request/);
    assert.match(text, /Domains:uploads\.example\.net/);
    assert.doesNotMatch(text, /Credentials:/);
  } finally {
    restore();
  }
});

test("an up-front request with domains and credentials labels both", async () => {
  const restore = installDom();
  try {
    const text = await renderText(
      request({
        domains: ["api.example.com"],
        vault_paths: ["demo/api-key"],
        names: ["Example API"],
        descriptions: ["read-only"],
      }),
    );
    assert.match(text, /Access Request/);
    assert.match(text, /Domains:api\.example\.com.*Credentials:Example API/);
  } finally {
    restore();
  }
});
