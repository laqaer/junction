import { useEffect, useId, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { site } from "../data/site";
import { track } from "../lib/analytics";

/**
 * The install block (site-spec §2.1). Until a package is published
 * (`site.installOneLiner === ""`) every tab shows the honest three-line source
 * quickstart and the CTA reads "Copy the quickstart"; the pipx/uv/npm tabs say
 * so instead of pretending. The version chip is labelled: it is the pyproject
 * version, and there is no tagged release yet.
 */
type Tab = "pipx" | "uv" | "npm" | "source";
const TABS: Tab[] = ["pipx", "uv", "npm", "source"];

const QUICKSTART = [
  `git clone ${site.githubRepo}.git && cd junction`,
  "bash minimal_install.sh",
  `${site.cli} setup && ${site.cli} up`,
];

const ONE_LINER: Record<Exclude<Tab, "source">, string> = {
  pipx: `pipx install ${site.installOneLiner}`,
  uv: `uv tool install ${site.installOneLiner}`,
  npm: `npm i -g ${site.installOneLiner}`,
};

export default function InstallTabs() {
  const published = site.installOneLiner !== "";
  const [tab, setTab] = useState<Tab>(published ? "pipx" : "source");
  const [copied, setCopied] = useState(false);
  const timer = useRef(0);
  const id = useId();

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const lines = published && tab !== "source" ? [ONE_LINER[tab]] : QUICKSTART;
  const copy = async () => {
    const text = lines.join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch { /* the block is still selectable by hand */ }
      ta.remove();
    }
    setCopied(true);
    track("install_copy", { tab });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1800);
  };

  const onKey = (e: React.KeyboardEvent) => {
    const i = TABS.indexOf(tab);
    if (e.key === "ArrowRight") { e.preventDefault(); setTab(TABS[(i + 1) % TABS.length]); }
    if (e.key === "ArrowLeft") { e.preventDefault(); setTab(TABS[(i - 1 + TABS.length) % TABS.length]); }
  };

  return (
    <div className="install" id="install">
      <div className="install-top">
        <div role="tablist" aria-label="Install method" className="tabs" onKeyDown={onKey}>
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              type="button"
              id={`${id}-tab-${t}`}
              aria-selected={tab === t}
              aria-controls={`${id}-panel`}
              tabIndex={tab === t ? 0 : -1}
              className={`tab ${tab === t ? "on" : ""}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <span className="chip" title="Version in pyproject.toml; no tagged release exists yet">
          v{site.version} · pyproject · no tagged release yet
        </span>
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${tab}`} className="panel">
        {!published && tab !== "source" && (
          <p className="caption panel-note">
            <code>{tab === "npm" ? "npm i -g" : tab === "uv" ? "uv tool install" : "pipx install"} {site.cli}</code> is not published yet. From source, today:
          </p>
        )}
        <pre className="install-pre" tabIndex={0}><code>{lines.map((l, i) => (
          <span className="line" key={i}><span className="prompt" aria-hidden="true">$ </span>{l}{"\n"}</span>
        ))}</code></pre>
        <p className="caption" data-alias>
          <code>{site.cli}</code> is also available as <code>{site.cliAlias}</code> · macOS and Linux · Python 3.10+ and Node 22+ · the agent CLI you already use
        </p>
      </div>
      <div className="install-actions">
        <button type="button" className="btn btn-primary" onClick={copy} aria-live="off">
          {copied ? <Check className="lucide" aria-hidden="true" /> : <Copy className="lucide" aria-hidden="true" />}
          {published && tab !== "source" ? "Copy the install command" : "Copy the quickstart"}
        </button>
        <span className="sr-only" aria-live="polite">{copied ? "Copied" : ""}</span>
        <span className="caption copied" aria-hidden="true">{copied ? "Copied" : ""}</span>
      </div>
    </div>
  );
}
