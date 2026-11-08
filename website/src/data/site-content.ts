// Copy and links for the YuBen website. Copy follows the approved Paper artboards
// (desktop 4AN-0, mobile 4OS-0, menu 4UC-0) on 2026-11-07, including line breaks.
import stars from './stars.json';

export const repoUrl = 'https://github.com/shkuratovdesigner/yuben-app';
export const docsUrl = `${repoUrl}#readme`;
export const command = 'npx yuben-app@latest';
export const starCount: number = stars.count;

export const nav = [
  { label: 'How it works', href: '#how-it-works' },
  { label: 'Features', href: '#features' },
  { label: 'Docs', href: docsUrl },
] as const;

export const demo = {
  src: '/media/yuben-demo-light.mp4',
  poster: '/media/yuben-demo-light-poster.webp',
  width: 1440,
  height: 750,
  label: 'YuBen demo',
  description:
    'YuBen demo: enter a topic, compare standout YouTube videos, and explore title patterns and a video plan.',
};

export const features = [
  {
    id: 'question',
    title: 'Start with a question',
    body: 'A topic, a format, and a little curiosity. YuBen takes it from there',
    bodyWidth: 331,
    shot: { name: 'composer', alt: 'YuBen composer with a research topic typed in and title analysis switched on' },
  },
  {
    id: 'winners',
    title: 'Find the unexpected winners',
    body: 'Small channel. Big response. Those are the videos worth studying',
    bodyWidth: 423,
    shot: { name: 'ranked', alt: 'YuBen report ranking the highest-performing videos, with views and outperformance multipliers' },
  },
  {
    id: 'ideas',
    title: 'See the idea behind the views',
    body: 'Turn repeated title patterns into a direction for your next video',
    bodyWidth: 358,
    shot: { name: 'analysis', alt: 'YuBen title analysis listing the common title patterns behind the outliers' },
  },
] as const;

export const shorts = [
  { id: 'R24JLVqW9pg', thumb: '/media/short-r24jlvqw9pg.webp', label: 'Play the first YuBen Short' },
  { id: 'opb18eNVrn0', thumb: '/media/short-opb18envrn0.webp', label: 'Play the second YuBen Short' },
] as const;

export const models = [
  { name: 'Anthropic API', icon: '/media/model-claude.svg' },
  { name: 'Claude Code', icon: '/media/model-claude.svg' },
  { name: 'OpenAI API', icon: '/media/model-openai.svg' },
  { name: 'Google Gemini', icon: '/media/model-gemini.svg' },
  { name: 'OpenRouter', icon: '/media/model-openrouter.svg' },
  { name: 'Ollama', icon: '/media/model-ollama.svg' },
] as const;

// Answers summarise the app README (2026-11-07): requirements, adapters and licence.
export const faq = [
  {
    q: 'What do I need to get started?',
    a: 'Node.js, a YouTube API key, and your preferred AI provider. Run the command to begin.',
  },
  {
    q: 'Can I use my own AI model?',
    a: 'Yes. Paste an Anthropic, OpenAI, Gemini or OpenRouter key, run a local Ollama model with no key at all, or use a coding CLI you already have, such as Claude Code. Your provider’s usual costs may apply.',
  },
  {
    q: 'Is YuBen free and open source?',
    a: 'Yes. YuBen is MIT-licensed and runs on your machine, so your keys and research stay with you. A typical run uses about 1,400 of YouTube’s 10,000 free daily API units.',
  },
] as const;

// Verified against the portfolio's src/data/public-content.ts on 2026-11-07.
export const socials = [
  { label: 'X', href: 'https://x.com/Shkuratovdesign', icon: '/media/social-x.svg', w: 22, mw: 24 },
  { label: 'YouTube', href: 'https://www.youtube.com/@EvgenyShkuratovDesigner', icon: '/media/social-youtube.svg', w: 28, mw: 24 },
  { label: 'Instagram', href: 'https://www.instagram.com/evgeny.shkuratov/', icon: '/media/social-instagram.svg', w: 22, mw: 24 },
  { label: 'LinkedIn', href: 'https://www.linkedin.com/in/evgeny-shkuratov-b34a99174/', icon: '/media/social-linkedin.svg', w: 22, mw: 24 },
  { label: 'GitHub', href: 'https://github.com/shkuratovdesigner', icon: '/media/social-github.svg', w: 22, mw: 24 },
] as const;
