# Third-Party Notices

This frontend bundles Twemoji SVG assets and variable WOFF2 fonts locally and ships Mermaid in the JavaScript bundle.

## Twemoji

- Project: `jdecked/twemoji`
- Source: https://github.com/jdecked/twemoji
- Frontend dependency alias: `jdecked-twemoji-assets`
- Assets used: SVG emoji graphics bundled locally at build time
- Graphics license: Creative Commons Attribution 4.0 International (`CC-BY-4.0`)

## Mermaid

- Project: `mermaid-js/mermaid`
- Source: https://github.com/mermaid-js/mermaid
- Frontend dependency: `mermaid`
- Usage: diagram rendering for ` ```mermaid ` code fences, loaded as a lazy chunk in the browser
- License: MIT

## Fonts

- Geist and Geist Mono: [Vercel Geist](https://github.com/vercel/geist-font), weights 100–900, Latin variable WOFF2
- Source Serif 4: [Adobe Source Serif](https://github.com/adobe-fonts/source-serif), weights 200–900, Latin variable WOFF2 from Google Fonts
- License: SIL Open Font License 1.1
- Bundled license notices: [Geist](public/fonts/LICENSE-Geist.txt) and [Source Serif 4](public/fonts/LICENSE-SourceSerif4.txt)

Review the upstream projects for the full license texts and attribution requirements before distributing builds that include bundled emoji assets.
