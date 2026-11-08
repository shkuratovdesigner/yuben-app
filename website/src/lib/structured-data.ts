// schema.org JSON-LD for search engines and AI answer engines. Built from the same
// data as the visible page (FAQ, features, command), so the two cannot drift apart.
import { command, faq, features, models, repoUrl, socials } from '../data/site-content';

export const siteUrl = 'https://yubenapp.org/';
export const shareImage = `${siteUrl}media/og-yuben-2026-11-08.jpg`;

const author = {
  '@type': 'Person',
  '@id': 'https://www.shkuratovdesigner.com/#person',
  name: 'Evgeny Shkuratov',
  jobTitle: 'Product Design Engineer',
  url: 'https://www.shkuratovdesigner.com',
  sameAs: socials.map((s) => s.href),
};

export function structuredData() {
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'WebSite',
        '@id': `${siteUrl}#website`,
        url: siteUrl,
        name: 'YuBen',
        description: 'Find YouTube outliers, spot the patterns behind them, and plan your next video.',
        inLanguage: 'en',
        publisher: { '@id': author['@id'] },
      },
      {
        '@type': 'SoftwareApplication',
        '@id': `${siteUrl}#app`,
        name: 'YuBen',
        url: siteUrl,
        description:
          'Local-first, open-source YouTube research app. Type a topic and YuBen finds outlier videos that earn far more views than their channel size predicts (views ÷ subscribers), then explains why with a ranked watch list, title-pattern analysis and a plan for your own video.',
        applicationCategory: 'MultimediaApplication',
        applicationSubCategory: 'YouTube content research',
        operatingSystem: 'macOS, Windows, Linux',
        softwareRequirements: 'Node.js 22 or newer, a YouTube Data API key, and an AI provider (Anthropic, OpenAI, Gemini, OpenRouter, Ollama or a coding CLI such as Claude Code)',
        installUrl: 'https://www.npmjs.com/package/yuben-app',
        downloadUrl: 'https://www.npmjs.com/package/yuben-app',
        codeRepository: repoUrl,
        license: 'https://opensource.org/licenses/MIT',
        isAccessibleForFree: true,
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
        featureList: [
          ...features.map((f) => `${f.title}: ${f.body}.`),
          `Works with ${models.map((m) => m.name).join(', ')}.`,
          `Install and start with one command: ${command}`,
        ],
        image: shareImage,
        screenshot: features.map((f) => `${siteUrl}media/app-${f.shot.name}-1800.webp`),
        author: { '@id': author['@id'] },
      },
      author,
      {
        '@type': 'FAQPage',
        '@id': `${siteUrl}#faq`,
        mainEntity: faq.map((item) => ({
          '@type': 'Question',
          name: item.q,
          acceptedAnswer: { '@type': 'Answer', text: item.a },
        })),
      },
    ],
  };
}

/** Serialised for a <script type="application/ld+json"> tag; `<` is escaped so no text can close the tag. */
export function structuredDataScript() {
  return JSON.stringify(structuredData()).replace(/</g, '\\u003c');
}
