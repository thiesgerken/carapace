# Artifact design

Start with the reader's task: a report leads with its decision, a dashboard with
its useful comparison, and a tool with the inputs needed for one result. Give the
page a specific title. Remove decoration and metrics that do not help that task.

## Theme tokens

The frame cannot read carapace's selected theme. Use the browser's color scheme,
not parent-page classes or storage. Define colors once on `:root`, then override
those tokens in a `prefers-color-scheme: dark` block. A restrained teal is the
default accent; use it for emphasis and controls, not every surface.

## Agent-output typography

Match carapace's `.chat-copy-serif`: **Source Serif 4** for body and headings,
**Geist** for controls, labels, and numbers, and **Geist Mono** for code. Use one
Google Fonts stylesheet link, requesting only the weights used by the page:

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;600&amp;family=Geist+Mono&amp;family=Source+Serif+4:wght@400;700&amp;display=swap">
```

```css
:root {
  color-scheme: light dark;
  --bg: #f4f7f8;
  --surface: #ffffff;
  --fg: #18343a;
  --muted: #52676b;
  --border: #c4d3d7;
  --accent: #236b86;
  --on-accent: #ffffff;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.25rem;
  --text-xl: clamp(1.75rem, 5vw, 2.5rem);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101c20;
    --surface: #18292e;
    --fg: #edf5f6;
    --muted: #b1c5c9;
    --border: #466168;
    --accent: #77cbd0;
    --on-accent: #102322;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: var(--text-base)/1.6 "Source Serif 4", ui-serif, Georgia, serif;
}
h1 { font-size: var(--text-xl); line-height: 1.15; }
h2 { font-size: var(--text-lg); line-height: 1.3; }
button, input, label, summary, small, figcaption, dt, dd, output, .meta, svg text {
  font-family: "Geist", system-ui, sans-serif;
}
code, pre { font-family: "Geist Mono", ui-monospace, monospace; }
small, figcaption { font-size: var(--text-sm); color: var(--muted); }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
```

Keep system fallbacks so the page remains readable if fonts fail to load. Body
text uses weight 400, headings 700, and emphasized controls 600 in the examples.
Do not request unused weights or load font CSS from another origin.

## Layout at 375px

- Include `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- Start with one column and 16px side gutters. Bound desktop reading width instead
  of stretching paragraphs across the screen. Use spacing in a small rhythm such
  as 8, 16, 24, and 32px.
- Let headings wrap; do not force fixed-height hero areas. Use `min-width: 0` on
  grid children and `overflow-wrap: anywhere` for user-supplied long strings.
- Use intrinsic grids rather than a fixed two-column layout:

  ```css
  main { width: min(100% - 2rem, 64rem); margin: 2rem auto; }
  .grid { display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); }
  .grid > * { min-width: 0; }
  svg, img { display: block; max-width: 100%; height: auto; }
  ```

- Keep dense tables as tables. If they genuinely need more width, place them in a
  labeled keyboard-focusable horizontal scroll region. Do not hide overflow on
  the body to conceal a broken layout.
- Keep controls at least 44px high, with visible labels and enough spacing for
  touch. A narrow viewport must not require hover to discover an action.

## Accessibility and trustworthy content

Use `lang`, a real `<title>`, one main heading, ordered heading levels, and semantic
`main`, `section`, `table`, `button`, `label`, and `output` elements. Native controls
beat custom widgets. Use a visible focus ring and logical document/tab order.
Do not make a whole card clickable with a hidden link.

Check normal text at 4.5:1 contrast and large text/meaningful graphics at 3:1 in
both themes. Do not use color as the only indication of status or chart series:
add words, labels, patterns, or symbols. Respect `prefers-reduced-motion` if you
add motion; most artifacts need none.

Describe meaningful SVGs with `role="img"`, a title, and a useful description.
Provide actual values in accessible text or a data table when a chart otherwise
hides them. Use `aria-live="polite"` for locally calculated results, not for the
whole page. Associate validation instructions with their inputs.

State units, time ranges, assumptions, and whether data is sampled, estimated, or
incomplete. Never dress invented numbers up as the user's real measurements.
Keep external sources and destination links in the chat reply: artifact code
must not navigate, open windows, or submit to a server.
