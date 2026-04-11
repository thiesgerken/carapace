# Carapace Frontend

Web UI for Carapace, built with Next.js (App Router).

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

## Code Style

- Use [Lucide](https://lucide.dev/icons) for all icons — import from `lucide-react`
- Use Tailwind CSS utility classes for styling; avoid custom CSS
- Use `clsx` / `tailwind-merge` for conditional class composition
- Components live in `src/components/`, hooks in `src/hooks/`
- Lint with `pnpm lint`
