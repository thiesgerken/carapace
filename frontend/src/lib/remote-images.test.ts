import assert from "node:assert/strict";
import test from "node:test";

import { installDom } from "../../test/react-test-utils";

import { isSameOriginUrl, stripRemoteSvgImages } from "./remote-images";

test("only URLs on our own origin count as same-origin", () => {
  const restore = installDom("https://carapace.example.test/chat");
  try {
    assert.equal(isSameOriginUrl("/emoji/1f600.svg"), true);
    assert.equal(isSameOriginUrl("diagram.png"), true);
    assert.equal(isSameOriginUrl("https://carapace.example.test/api/x.png"), true);
    assert.equal(isSameOriginUrl("https://evil.example/?q=secret"), false);
    assert.equal(isSameOriginUrl("//evil.example/x.png"), false);
    assert.equal(isSameOriginUrl(""), false);
  } finally {
    restore();
  }
});

test("remote SVG images are removed, local ones kept", () => {
  const restore = installDom("https://carapace.example.test/");
  try {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/?q=secret"/>' +
      '<image href="/emoji/1f600.svg"/><text>label</text></svg>';
    const cleaned = stripRemoteSvgImages(svg);
    assert.doesNotMatch(cleaned, /evil\.example/);
    assert.match(cleaned, /\/emoji\/1f600\.svg/);
    assert.match(cleaned, /label/);
  } finally {
    restore();
  }
});
