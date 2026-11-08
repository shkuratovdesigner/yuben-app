import { useEffect, useRef, useState } from 'react';
import { command } from '../data/site-content';
import { CheckIcon, CopyIcon } from './icons';
import { trackCommandCopy, type CommandPlacement } from '../lib/analytics';

type Status = 'idle' | 'copied' | 'failed';

/** Rounded command field. Shows success only after the clipboard write resolves. */
export function InstallCommand({ id, placement }: { id: string; placement: CommandPlacement }) {
  const [status, setStatus] = useState<Status>('idle');
  const codeRef = useRef<HTMLElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const attempt = useRef(0);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const selectCommand = () => {
    const node = codeRef.current;
    const selection = window.getSelection();
    if (!node || !selection) return;
    const range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
  };

  const copy = async () => {
    const current = ++attempt.current;
    window.clearTimeout(timer.current);
    let ok = false;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(command);
      ok = true;
    } catch {
      ok = false;
    }
    trackCommandCopy(placement, ok);
    if (current !== attempt.current) return;
    setStatus(ok ? 'copied' : 'failed');
    if (!ok) selectCommand();
    timer.current = window.setTimeout(() => setStatus('idle'), ok ? 1800 : 5000);
  };

  const copied = status === 'copied';
  return (
    <div className="install" data-status={status}>
      <div className="install-field">
        <code ref={codeRef} id={id} className="install-command">
          {command}
        </code>
        <button type="button" className="btn-teal install-copy" onClick={copy} aria-describedby={id}>
          {/* Two stacked layers, each icon + word centred on its own, so the
              shorter "Copy" is not pushed off-centre by room kept for "Copied". */}
          <span className="install-states" aria-hidden="true">
            <span className="install-state" data-on={!copied}>
              <span className="install-icon"><CopyIcon /></span>
              <span>Copy</span>
            </span>
            <span className="install-state" data-on={copied}>
              <span className="install-icon"><CheckIcon /></span>
              <span>Copied</span>
            </span>
          </span>
          <span className="sr-only">Copy install command</span>
        </button>
      </div>
      <p className="install-hint" role="status">
        {status === 'failed' && 'Copy blocked by the browser. The command is selected, press ⌘C or Ctrl+C'}
        {copied && <span className="sr-only">Command copied to clipboard</span>}
      </p>
    </div>
  );
}
