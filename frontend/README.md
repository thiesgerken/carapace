# carapace Frontend

Web UI for carapace, built with Next.js (App Router).

## Tech Stack

- **Framework:** [Next.js](https://nextjs.org) (App Router) with React 19
- **Language:** TypeScript
- **Styling:** [Tailwind CSS 4](https://tailwindcss.com)
- **Icons:** [Lucide React](https://lucide.dev) (`lucide-react`)
- **Fonts:** [Geist](https://vercel.com/font) via `next/font`
- **Markdown:** `react-markdown` with `remark-gfm`, `remark-math`, `rehype-katex`, `rehype-pretty-code`
- **Theming:** `next-themes` (light/dark mode)

## Getting Started

```bash
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

### Emoji Rendering

The frontend bundles Twemoji SVG assets locally at build time and replaces emoji in rendered assistant markdown and session titles.

The bundled assets are sourced from the maintained [jdecked/twemoji](https://github.com/jdecked/twemoji) repository, currently pinned in this frontend to `v17.0.2` via a GitHub tarball dependency.

The asset preparation step runs automatically before `pnpm dev` and `pnpm build`. It generates the ignored `src/lib/emoji.generated.ts` manifest and the ignored `public/emoji/` asset directory locally, so they do not need to live in git. No runtime CDN requests are used for emoji assets. Run `pnpm prepare:emoji` manually if you ever need to regenerate the bundled assets after changing the pinned Twemoji source.

See [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md) for the bundled emoji asset notices.

## Code Style

- Use [Lucide](https://lucide.dev/icons) for all icons — import from `lucide-react`
- Use Tailwind CSS utility classes for styling; avoid custom CSS
- Use `clsx` / `tailwind-merge` for conditional class composition
- Components live in `src/components/`, hooks in `src/hooks/`
- Lint with `pnpm lint`
