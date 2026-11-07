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
- Feature story (`feature-story.tsx`, `use-feature-scroll.ts`, `lib/story.ts`): at ≥1024×700 the copy sits in a sticky, vertically centred slot while the three real UI panels scroll normally. One passive, rAF-throttled scroll listener (gated by an IntersectionObserver) picks the panel nearest the viewport centre with a 24px hysteresis, so fast and reverse scrolls land on the right copy without stepping through skipped stages. The copy swap is a 200ms in / 150ms out cross-blur (2px). Smaller or shorter screens show three stacked blocks.
- Demo video (`demo-video.tsx`, `lib/playback.ts`): playback intent changes only through explicit actions; visibility and hidden tabs only suspend. Muted autoplay, loop, play/pause and sound buttons follow the real media state, rejected autoplay shows a Play button, a failed source shows a retry and a link. Reduced motion starts on the poster.
- Shorts open in an accessible `<dialog>` with a privacy-enhanced YouTube embed created on activation and removed on close; opening one pauses the demo.
- Motion tokens and recipes come from `skills/transitions-dev` (icon swap, accordion, soft text swap), with reduced-motion guards in `src/styles/motion.css`.

## Media provenance

| File | Source |
|---|---|
| `public/media/yuben-demo-light.mp4` | `ventures/portfolio/assets/cases-videos/yuben-demo-light-web-sound.mp4`, copied unchanged (SHA-1 `d14df8aa191c4afa4db96f080abfd21eb256f201`; 1440×750, 60 fps, 26.075 s, music and effects included) |
| `public/media/yuben-demo-light-poster.webp` | `ventures/portfolio/assets/cases-videos/yuben-demo-light-poster.webp`, unchanged |
| `public/media/cloud-sky.webp`, `cloud-sky-768.webp` | WebP derivatives (q82 full size, q80 768px) of `ventures/yuben/assets/website-2026-11-07/cloud-sky.png`; original kept. Static until an animated cloud asset is supplied: replace `--sky-image` in `src/styles/tokens.css` or swap `.sky-image` for a video |
| `public/media/thumb-1..3.jpg` | `ventures/portfolio/code/motion/public/yuben/thumbnails/` `5y0z8a2…`, `5akepcvz…`, `67mr8xhw…` (matched to the Paper fills by checksum) |
| `public/media/short-*.jpg`, `model-*.svg`, `social-*.svg` | `ventures/yuben/assets/website-2026-11-07/` (social icons are the colour versions) |
| `src/data/stars.json` | Last known GitHub star count; refreshed by `npm run build`, kept on failure |
