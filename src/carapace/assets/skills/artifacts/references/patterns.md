# Complete artifact patterns

Each fenced page is an independent `index.html`, not a component to assemble with
other files. Copy one to `/workspace/artifacts/<slug>/index.html`, replace its
sample content and title, and keep all resources inline. The repeated theme CSS
is intentional: each copied page must work on its own. External source links
belong in the chat reply, not inside the artifact.

## Report: decision first

Use for a review, recommendation, or explanation worth keeping. Lead with the
conclusion, distinguish evidence from assumptions, and let details expand without
sending the reader elsewhere.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Release readiness review</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;600&amp;family=Geist+Mono&amp;family=Source+Serif+4:wght@400;700&amp;display=swap">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' viewBox='0 0 32 32'%3E%3Cstyle%3E:root{color:%23236b86}@media(prefers-color-scheme:dark){:root{color:%2377cbd0}}%3C/style%3E%3Cpath fill='none' stroke='currentColor' stroke-width='2' d='M8 3h11l5 5v21H8zM18 3v7h6M12 15h8m-8 5h8m-8 5h5'/%3E%3C/svg%3E">
  <style>
    :root { color-scheme: light dark; --bg: #f4f7f8; --surface: #fff; --fg: #18343a; --muted: #52676b; --border: #c4d3d7; --accent: #236b86; }
    @media (prefers-color-scheme: dark) {
      :root { --bg: #101c20; --surface: #18292e; --fg: #edf5f6; --muted: #b1c5c9; --border: #466168; --accent: #77cbd0; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--fg); font: 1rem/1.6 "Source Serif 4", ui-serif, Georgia, serif; }
    main { width: min(100% - 2rem, 48rem); margin: 2rem auto; overflow-wrap: anywhere; }
    h1 { font-size: clamp(1.75rem, 5vw, 2.5rem); line-height: 1.15; }
    h2 { font-size: 1.25rem; }
    header { border-top: 4px solid var(--accent); }
    .lede { font-size: 1.25rem; line-height: 1.6; }
    .meta { color: var(--muted); font-size: .875rem; }
    section { margin-top: 1.5rem; }
    details { padding: 1rem; border: 1px solid var(--border); background: var(--surface); }
    summary { cursor: pointer; min-height: 44px; padding-block: .5rem; font-weight: 600; }
    :focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
    button, input, label, summary, .meta, figcaption, dt, dd, output, svg text { font-family: "Geist", system-ui, sans-serif; }
    code, pre { font-family: "Geist Mono", ui-monospace, monospace; }
  </style>
</head>
<body>
  <main>
    <header>
      <p class="meta">Sample assessment · 12 March 2026</p>
      <h1>Release readiness review</h1>
      <p class="lede">Proceed with a limited rollout. Keep the rollback window open until the first cohort completes onboarding.</p>
    </header>
    <section aria-labelledby="decision">
      <h2 id="decision">Decision and scope</h2>
      <p>Start with one volunteer team rather than a company-wide release. This tests the onboarding path while keeping support demand bounded.</p>
    </section>
    <section aria-labelledby="conditions">
      <h2 id="conditions">Conditions before widening access</h2>
      <ul>
        <li>Verify that restoring the previous version preserves saved work.</li>
        <li>Assign a support owner for the first two business days.</li>
        <li>Ask the pilot team whether the setup instructions are sufficient.</li>
      </ul>
    </section>
    <section aria-labelledby="evidence">
      <h2 id="evidence">Evidence and uncertainty</h2>
      <details>
        <summary>Read the assessment basis</summary>
        <p>This example assumes that functional checks have passed but onboarding has not been observed with a new team. A successful pilot would reduce that uncertainty; it would not establish long-term reliability.</p>
      </details>
    </section>
  </main>
</body>
</html>
```

## Dashboard: one useful comparison

Use for several related measurements that need a shared context. This example
uses inline SVG rather than loading a library for four bars. Each bar starts at
the same zero baseline; the exact values remain readable without hover.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Support workload overview</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;600&amp;family=Geist+Mono&amp;family=Source+Serif+4:wght@400;700&amp;display=swap">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' viewBox='0 0 32 32'%3E%3Cstyle%3E:root{color:%23236b86}@media(prefers-color-scheme:dark){:root{color:%2377cbd0}}%3C/style%3E%3Cpath fill='currentColor' d='M5 18h5v11H5zM13 10h5v19h-5zM21 3h5v26h-5z'/%3E%3C/svg%3E">
  <style>
    :root { color-scheme: light dark; --bg: #f4f7f8; --surface: #fff; --fg: #18343a; --muted: #52676b; --border: #c4d3d7; --accent: #236b86; }
    @media (prefers-color-scheme: dark) {
      :root { --bg: #101c20; --surface: #18292e; --fg: #edf5f6; --muted: #b1c5c9; --border: #466168; --accent: #77cbd0; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--fg); font: 1rem/1.6 "Source Serif 4", ui-serif, Georgia, serif; }
    main { width: min(100% - 2rem, 64rem); margin: 2rem auto; overflow-wrap: anywhere; }
    h1 { font-size: clamp(1.75rem, 5vw, 2.5rem); line-height: 1.15; }
    h2 { font-size: 1.25rem; margin-top: 0; }
    .meta, figcaption, dt { color: var(--muted); font-size: .875rem; }
    .grid { display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); }
    .grid > * { min-width: 0; padding: 1rem; border: 1px solid var(--border); background: var(--surface); }
    figure { margin: 0; }
    svg { display: block; width: 100%; height: auto; }
    svg text { fill: var(--fg); font: 22px system-ui, sans-serif; }
    .bar { fill: var(--accent); }
    .baseline { stroke: var(--fg); }
    dd { margin: 0 0 1rem; font-size: 1.75rem; font-variant-numeric: tabular-nums; }
    button, input, label, summary, .meta, figcaption, dt, dd, output, svg text { font-family: "Geist", system-ui, sans-serif; }
    code, pre { font-family: "Geist Mono", ui-monospace, monospace; }
  </style>
</head>
<body>
  <main>
    <header>
      <p class="meta">Sample data · four completed weeks</p>
      <h1>Support workload overview</h1>
      <p>Resolution volume is steady enough to keep the current staffing plan. Review the oldest open requests before adding new work.</p>
    </header>
    <div class="grid">
      <section aria-labelledby="volume-heading">
        <h2 id="volume-heading">Resolved requests</h2>
        <figure>
          <svg viewBox="0 0 480 260" role="img" aria-labelledby="chart-title chart-desc">
            <title id="chart-title">Resolved support requests by week</title>
            <desc id="chart-desc">Sample data: week 1, 42 requests; week 2, 50; week 3, 48; week 4, 57. Bars share a zero baseline.</desc>
            <line class="baseline" x1="20" y1="220" x2="460" y2="220" />
            <rect class="bar" x="45" y="94" width="65" height="126" />
            <rect class="bar" x="155" y="70" width="65" height="150" />
            <rect class="bar" x="265" y="76" width="65" height="144" />
            <rect class="bar" x="375" y="49" width="65" height="171" />
            <g text-anchor="middle">
              <text x="77.5" y="82">42</text><text x="187.5" y="58">50</text>
              <text x="297.5" y="64">48</text><text x="407.5" y="37">57</text>
              <text x="77.5" y="246">Week 1</text><text x="187.5" y="246">Week 2</text>
              <text x="297.5" y="246">Week 3</text><text x="407.5" y="246">Week 4</text>
            </g>
            <text x="20" y="214">0</text>
          </svg>
          <figcaption>Requests resolved per week, not cumulative totals.</figcaption>
        </figure>
      </section>
      <section aria-labelledby="queue-heading">
        <h2 id="queue-heading">Current queue</h2>
        <dl>
          <dt>Open requests</dt><dd>18</dd>
          <dt>Oldest request</dt><dd>3 days</dd>
        </dl>
        <p>Age is measured from the first customer message. The open queue is a point-in-time snapshot, not part of the weekly totals.</p>
      </section>
    </div>
  </main>
</body>
</html>
```

## Interactive tool: local capacity estimate

Use for a calculation the reader benefits from changing. Inputs stay in memory;
there is no storage, navigation, form submission, or network call. The output
explains its unit and rejects invalid inputs instead of silently replacing them.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Delivery capacity estimator</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;600&amp;family=Geist+Mono&amp;family=Source+Serif+4:wght@400;700&amp;display=swap">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' viewBox='0 0 32 32'%3E%3Cstyle%3E:root{color:%23236b86}@media(prefers-color-scheme:dark){:root{color:%2377cbd0}}%3C/style%3E%3Crect x='5' y='3' width='22' height='26' rx='3' fill='none' stroke='currentColor' stroke-width='2'/%3E%3Cpath fill='none' stroke='currentColor' stroke-width='2' d='M9 9h14M10 17h4m-2-2v4m7-2h4M10 24h4m5 0h4'/%3E%3C/svg%3E">
  <style>
    :root { color-scheme: light dark; --bg: #f4f7f8; --surface: #fff; --fg: #18343a; --muted: #52676b; --border: #c4d3d7; --accent: #236b86; --on-accent: #fff; }
    @media (prefers-color-scheme: dark) {
      :root { --bg: #101c20; --surface: #18292e; --fg: #edf5f6; --muted: #b1c5c9; --border: #466168; --accent: #77cbd0; --on-accent: #102322; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--fg); font: 1rem/1.6 "Source Serif 4", ui-serif, Georgia, serif; }
    main { width: min(100% - 2rem, 40rem); margin: 2rem auto; overflow-wrap: anywhere; }
    h1 { font-size: clamp(1.75rem, 5vw, 2.5rem); line-height: 1.15; }
    .meta { color: var(--muted); font-size: .875rem; }
    #estimate-inputs { display: grid; gap: 1rem; padding: 1.5rem; border: 1px solid var(--border); background: var(--surface); }
    label { display: grid; gap: .25rem; }
    input, button { width: 100%; min-height: 44px; padding: .625rem; border: 1px solid var(--border); border-radius: .25rem; font: inherit; }
    input { background: var(--bg); color: var(--fg); }
    button { border-color: var(--accent); background: var(--accent); color: var(--on-accent); cursor: pointer; font-weight: 600; }
    output { display: block; margin-block: 1.5rem; font-size: 1.25rem; font-weight: 600; }
    :focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
    button, input, label, summary, .meta, figcaption, dt, dd, output, svg text { font-family: "Geist", system-ui, sans-serif; }
    code, pre { font-family: "Geist Mono", ui-monospace, monospace; }
  </style>
</head>
<body>
  <main>
    <header>
      <p class="meta">Local calculator · illustrative inputs</p>
      <h1>Delivery capacity estimator</h1>
      <p id="assumptions">Multiply people, focused hours per person per week, and weeks. This is an upper bound before unplanned work, not a delivery commitment.</p>
    </header>
    <div id="estimate-inputs" role="group" aria-label="Capacity inputs" aria-describedby="assumptions input-help">
      <label for="people">People
        <input id="people" name="people" type="number" min="1" max="100" step="1" value="4" required aria-describedby="input-help">
      </label>
      <label for="hours">Focused hours per person per week
        <input id="hours" name="hours" type="number" min="1" max="40" step="1" value="24" required aria-describedby="input-help">
      </label>
      <label for="weeks">Weeks
        <input id="weeks" name="weeks" type="number" min="1" max="52" step="1" value="2" required aria-describedby="input-help">
      </label>
      <p id="input-help" class="meta">Whole numbers only: 1–100 people, 1–40 hours, and 1–52 weeks.</p>
      <button type="button" id="calculate">Calculate capacity</button>
    </div>
    <output id="result" for="people hours weeks" aria-live="polite"></output>
    <p class="meta">No inputs leave this page. Refreshing resets the example values.</p>
  </main>
  <script>
    const inputs = document.getElementById("estimate-inputs");
    const people = document.getElementById("people");
    const hours = document.getElementById("hours");
    const weeks = document.getElementById("weeks");
    const result = document.getElementById("result");
    function calculate() {
      if (!people.checkValidity() || !hours.checkValidity() || !weeks.checkValidity()) {
        result.textContent = "Enter whole numbers within the ranges shown above.";
        return;
      }
      const total = people.valueAsNumber * hours.valueAsNumber * weeks.valueAsNumber;
      result.textContent = `${new Intl.NumberFormat().format(total)} person-hours of planned capacity`;
    }
    inputs.addEventListener("input", calculate);
    document.getElementById("calculate").addEventListener("click", calculate);
    calculate();
  </script>
</body>
</html>
```
