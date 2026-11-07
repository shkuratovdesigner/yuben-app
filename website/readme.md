# YuBen website

Marketing site for YuBen. An independent package inside the YuBen repository: it does not touch the local app (`frontend/`, `backend/`), its onboarding routes or the npm installer payload, and it needs no backend or credentials.

Design source: Paper file `01M54W6RDTK4P67J35WWPWBE8P`, page `p-B-0`: [desktop](https://app.paper.design/file/01M54W6RDTK4P67J35WWPWBE8P/p-B-0/4AN-0), [mobile](https://app.paper.design/file/01M54W6RDTK4P67J35WWPWBE8P/p-B-0/4OS-0), [mobile menu](https://app.paper.design/file/01M54W6RDTK4P67J35WWPWBE8P/p-B-0/4UC-0). Implementation plan: `ai-os/ventures/yuben/plans/001-website-implementation.md`.

## Commands

```bash
npm install
npm run dev          # http://127.0.0.1:5288
npm run build        # refreshes the star count, typechecks, builds and prerenders dist/
npm run build:offline  # same without the GitHub star request
npm run preview      # serves dist/ at http://127.0.0.1:5289
npm run lint && npm run typecheck
npm test             # unit tests: stage selection and video intent
npm run test:e2e     # Playwright, Chromium + WebKit, desktop + mobile (uses the preview server)
```

## Hosting

Static site. Deployment root `website/`, build command `npm run build`, output `dist/`. Not deployed; no domain is configured, so the page emits no canonical or absolute Open Graph URLs. Add them once a domain exists.

## How it is built

- React 19 + TypeScript + Vite, plain CSS. `src/entry-server.tsx` renders the page at build time (`scripts/prerender.mjs`); the client hydrates it. All content is readable with JavaScript off.
- `src/data/site-content.ts` holds the copy, links and media paths. Desktop and mobile copy differ slightly in Paper; `only-d` / `only-m` spans keep both exact.
- Layout (768px and up): header, footer and the hero/closing sky cards share one frame edge, `max(20px, 3.5vw)` from the viewport. Content sections use a `max(48px, 8.333vw)` gutter inside a 1600px container; the demo fills the hero card with a 28px inset, capped to that container.
- Feature story (`feature-story.tsx`, `feature-panels.tsx`, `use-feature-scroll.ts`, `lib/story.ts`): at ≥1024×700 the copy sits in a sticky, vertically centred slot. Each real app screenshot sits in a full-height sticky box, scrolls in, holds level with the copy, then scrolls on. The pinned scroll is split into three equal parts (first and last steps hold longer), with a 24px hysteresis, so fast and reverse scrolls land on the right copy. The copy swap is a 200ms in / 150ms out cross-blur (2px). Smaller or shorter screens show three stacked blocks.
- Demo video (`demo-video.tsx`, `lib/playback.ts`): playback intent changes only through explicit actions; visibility and hidden tabs only suspend. Muted autoplay, loop, play/pause and sound buttons follow the real media state, rejected autoplay shows a Play button, a failed source shows a retry and a link. Reduced motion starts on the poster.
- Shorts play in place: activating a card swaps its thumbnail for a privacy-enhanced YouTube embed inside the same card. One plays at a time; starting one pauses the demo. Without JavaScript each card links to the Short on YouTube.
- Motion tokens and recipes come from `skills/transitions-dev` (icon swap, accordion, soft text swap), with reduced-motion guards in `src/styles/motion.css`.

## Media provenance

| File | Source |
|---|---|
| `public/media/yuben-demo-light.mp4` | `ventures/portfolio/assets/cases-videos/yuben-demo-light-web-sound.mp4`, copied unchanged (SHA-1 `d14df8aa191c4afa4db96f080abfd21eb256f201`; 1440×750, 60 fps, 26.075 s, music and effects included) |
| `public/media/yuben-demo-light-poster.webp` | `ventures/portfolio/assets/cases-videos/yuben-demo-light-poster.webp`, unchanged |
| `public/media/cloud-sky.webp`, `cloud-sky-768.webp` | WebP derivatives (q82 full size, q80 768px) of `ventures/yuben/assets/website-2026-11-07/cloud-sky.png`; original kept. Static until an animated cloud asset is supplied: replace `--sky-image` in `src/styles/tokens.css` or swap `.sky-image` for a video |
| `public/media/app-{composer,ranked,analysis}-{760,1264,1800}.webp` | Light-theme captures of the local YuBen app at 2x (2026-11-08, `scripts/capture-app-screenshots.mjs`). Composer with the query of the saved report "I Built My Own AI App From Scratch" (`r_24ef5e27…`), that report's ranked grid, and the title analysis of "Autonomous AI Agents" (`r_7226df8f…`), the nearest report with title analysis. To refresh: run the app (`YUBEN_PORT=8077 python3 yuben.py start --no-browser` in the repo root), then `node scripts/capture-app-screenshots.mjs` and re-export. |
| `public/media/short-*.jpg`, `model-*.svg`, `social-*.svg` | `ventures/yuben/assets/website-2026-11-07/` (social icons are the colour versions) |
| `src/data/stars.json` | Last known GitHub star count; refreshed by `npm run build`, kept on failure |
