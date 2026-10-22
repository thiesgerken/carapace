# Charts in artifacts

Use a chart only when its shape answers a question more clearly than a sentence
or table. A few comparable values usually belong in a chat table; a single number
usually needs no chart. Do not add a visualization merely to fill a dashboard.

## Pick the smallest implementation

| Situation | Choice |
| --- | --- |
| A short bar chart, a small trend, or a fixed annotated comparison | Inline SVG |
| Several datasets, local filtering, or tooltips that materially help inspection | Pinned Chart.js |
| Exact lookup matters more than the overall shape | Semantic HTML table |
| Relationships, states, or a process rather than measurements | Mermaid in chat |

Both implementations must use embedded data and local interactions only. No
runtime fetching, telemetry, remote images, or navigation. Library scripts are
allowed resource loads, not permission to call APIs.

## Inline SVG

Use a `viewBox` and responsive CSS instead of a fixed pixel width. Give the SVG
`role="img"`, a `<title>`, and a `<desc>` describing the comparison. Show units and
readable value labels; use a table if the number of labels becomes unwieldy.
Leave enough space for labels and do not clip them at 375px.

Build fills and strokes from the theme tokens in [design.md](design.md). The
teal accent can represent one series. For multiple series, add a restrained amber
and purple, with lighter dark-mode counterparts. Distinguish them with labels or
patterns as well as color. Check contrast rather than assuming that a hue works
in both themes. The dashboard in [patterns.md](patterns.md) is a complete SVG
example with no dependency.

## Pinned Chart.js

Use the classic UMD build from an exact release, for example:

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js"></script>
```

Alternatively use an exact npm version under
`https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.js`.
Do not use a moving tag, a version range, an unversioned import, another CDN, or a
CDN stylesheet. Keep all configuration and data inline. No remote-data plugins.

Place the canvas in a responsive, bounded container, give it a useful accessible
name, and provide the underlying values in a nearby semantic table. A canvas
bitmap alone is not an accessible dataset. Example configuration after creating
`<canvas id="volume" role="img" aria-label="Resolved requests by week; values in the table below"></canvas>`:

```js
const color = (token) => getComputedStyle(document.documentElement).getPropertyValue(token).trim();
const chart = new Chart(document.getElementById("volume"), {
  type: "bar",
  data: {
    labels: ["Week 1", "Week 2", "Week 3", "Week 4"],
    datasets: [{
      label: "Resolved requests (sample data)",
      data: [42, 50, 48, 57],
      backgroundColor: color("--accent"),
    }],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: { legend: { labels: { color: color("--fg") } } },
    scales: {
      x: { ticks: { color: color("--fg") }, grid: { display: false } },
      y: {
        beginAtZero: true,
        title: { display: true, text: "Requests", color: color("--fg") },
        ticks: { color: color("--fg"), precision: 0 },
        grid: { color: color("--border") },
      },
    },
  },
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  chart.data.datasets[0].backgroundColor = color("--accent");
  chart.options.plugins.legend.labels.color = color("--fg");
  for (const axis of Object.values(chart.options.scales)) {
    axis.ticks.color = color("--fg");
  }
  chart.options.scales.y.title.color = color("--fg");
  chart.options.scales.y.grid.color = color("--border");
  chart.update("none");
});
```

The wrapper, theme tokens, and data table belong in the same `index.html`. Give
the wrapper a height such as `18rem` so the canvas does not grow without a bound.
If the CDN is unavailable, leave the table readable and report that the chart
could not load; do not silently substitute made-up data.

## Reading integrity

Start bar/value axes at zero. A truncated line-chart axis can be useful, but label
its range plainly. Avoid 3D, dual axes that imply an unsupported relationship,
excess precision, and pie slices too small to compare. Label denominators for
percentages and the time range for every trend. Keep source URLs in the chat
reply rather than making the artifact navigate to them.
