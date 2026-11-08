import { DemoVideo } from './components/demo-video';
import { FeatureStory } from './components/feature-story';
import { PlusMinusIcon } from './components/icons';
import { InstallCommand } from './components/install-command';
import { ShortsGallery } from './components/shorts-gallery';
import { SiteHeader } from './components/site-header';
import { useReveal } from './hooks/use-reveal';
import { docsUrl, faq, models, repoUrl, socials } from './data/site-content';

export function App() {
  useReveal();
  return (
    <div className="page" id="top">
      <a className="skip-link" href="#main">Skip to content</a>
      <SiteHeader />
      <main id="main">
        <section className="hero sky" aria-labelledby="hero-title">
          <div className="sky-image" aria-hidden="true" />
          <div className="hero-fade" aria-hidden="true" />
          <div className="hero-copy">
            <h1 id="hero-title" className="hero-title">
              Find your next <br className="only-m" />great video idea<br />
              <em>See what’s <br className="only-m" />already working</em>
            </h1>
            <p className="hero-sub">Find YouTube outliers, spot the patterns, and make something worth watching</p>
          </div>
          <InstallCommand id="hero-command" placement="hero" />
          <DemoVideo />
        </section>

        <FeatureStory />

        <section className="shorts reveal" aria-labelledby="shorts-title">
          <div className="section-copy">
            <h2 id="shorts-title" className="section-title">Less reading<br />More seeing</h2>
            <p className="section-body shorts-body">Two quick looks at YuBen, from the person building it</p>
          </div>
          <ShortsGallery />
        </section>

        <section id="features" className="models reveal" aria-labelledby="models-title">
          <div className="section-copy">
            <h2 id="models-title" className="section-title">Your AI<br />Your choice</h2>
            <p className="section-body">
              Connect a model you already use.<br />Keep your research on your machine<span className="only-m">.</span>
            </p>
          </div>
          <ul className="model-grid">
            {models.map((m) => (
              <li key={m.name} className="model-card">
                <img src={m.icon} alt="" width="36" height="36" loading="lazy" />
                <span>{m.name}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="faq reveal" aria-labelledby="faq-title">
          <h2 id="faq-title" className="section-title faq-title">A few quick answers</h2>
          <div className="faq-list">
            {faq.map((item, i) => (
              <details key={item.q} className="faq-item" open={i === 0}>
                <summary>
                  <span>{item.q}</span>
                  <PlusMinusIcon />
                </summary>
                <div className="faq-answer"><p>{item.a}</p></div>
              </details>
            ))}
          </div>
        </section>

        <section className="closing sky reveal" aria-labelledby="closing-title">
          <div className="sky-image" aria-hidden="true" />
          <h2 id="closing-title" className="closing-title">Your next video <br className="only-m" />starts here</h2>
          <InstallCommand id="closing-command" placement="closing" />
        </section>
      </main>

      <footer className="site-footer">
        <p className="footer-brand">YuBen</p>
        <div className="footer-links">
          <a href={repoUrl}>GitHub ↗</a>
          <a href={docsUrl}>Documentation</a>
        </div>
        <p className="footer-credit">Made by Evgeny Shkuratov</p>
        <ul className="footer-socials">
          {socials.map((s) => (
            <li key={s.label}>
              <a href={s.href} aria-label={s.label} style={{ '--w': `${s.w}px`, '--mw': `${s.mw}px` } as React.CSSProperties}>
                <img src={s.icon} alt="" />
              </a>
            </li>
          ))}
        </ul>
      </footer>
    </div>
  );
}
