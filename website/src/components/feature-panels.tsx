import { rankedVideos } from '../data/site-content';

// Native HTML recreations of YuBen's light UI (Paper 4L8, 4LJ, 4LQ).
// `only-d` / `only-m` carry the small copy differences between the
// desktop and mobile artboards. Decorative: the step copy describes them.

export function ComposerPanel() {
  return (
    <div className="panel panel-composer" aria-hidden="true">
      <div className="ui ui-composer">
        <p className="ui-composer-title">What content are you<br />searching for?</p>
        <div className="ui-composer-box">
          <p className="ui-composer-query">I built my own AI app <br className="only-m" />from scratch</p>
          <div className="ui-composer-row">
            <span className="ui-accent">Long-form</span>
            <span className="ui-muted">Shorts</span>
            <span className="ui-muted ui-grow"><span className="only-d">All time ⌄</span></span>
            <span className="ui-send">↑</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function RankedPanel() {
  return (
    <div className="panel" aria-hidden="true">
      <div className="ui ui-card ui-ranked">
        <p className="ui-ranked-title">
          <span className="only-d">Top 36 Highest-Performed Videos</span>
          <span className="only-m">Top-performing videos</span>
        </p>
        <div className="ui-ranked-head">
          <span>Video</span>
          <span>Views ↓</span>
          <span>Mult ↓</span>
        </div>
        {rankedVideos.map((row) => (
          <div className="ui-ranked-row" key={row.thumb}>
            <span className="ui-ranked-thumb">
              <img src={row.thumb} alt="" width="150" height="84" loading="lazy" decoding="async" />
            </span>
            <span className="ui-ranked-views tabular">{row.views}</span>
            <span className="ui-chip tabular">{row.mult}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AnalysisPanel() {
  return (
    <div className="panel" aria-hidden="true">
      <div className="ui ui-card ui-analysis">
        <div className="ui-tabs">
          <span className="ui-accent">Title analysis</span>
          <span className="ui-muted only-d">Script analysis (off)</span>
        </div>
        <div className="ui-analysis-head only-d">
          <span>Common features</span>
          <span>Videos</span>
        </div>
        <div className="ui-feature">
          <div className="ui-feature-row">
            <span>First-person experiment</span>
            <span className="ui-muted only-d">7</span>
          </div>
          <p>“What 6 months of AI coding did to my dev team”</p>
        </div>
        <div className="ui-feature">
          <div className="ui-feature-row">
            <span>Concrete number or price<span className="only-d"> anchor</span></span>
            <span className="ui-muted only-d">6</span>
          </div>
          <p>“$400/Month”, “5 AI Employees”<span className="only-d">, “in 10 Minutes”</span></p>
        </div>
      </div>
    </div>
  );
}

export const featurePanels = [ComposerPanel, RankedPanel, AnalysisPanel];
