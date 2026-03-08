import React from "react";
import { getMetaValues, IIIFManifest } from "./MetadataUtils";
import worksIndex, { WorkEntry } from "./worksIndex";

function score(entry: WorkEntry, themes: string[], state: string): number {
  let s = 0;
  const entryThemes = entry.themes.map((t) => t.toLowerCase());
  for (const t of themes) {
    if (entryThemes.includes(t.toLowerCase())) s += 3;
  }
  if (state && entry.state && entry.state.toLowerCase() === state.toLowerCase()) s += 2;
  return s;
}

export default function SimilarWorks({ manifest }: { manifest: IIIFManifest }) {
  const rawThemes = getMetaValues(manifest, "Themes");
  const currentThemes = rawThemes
    .flatMap((t) => t.split(";").map((s) => s.trim()))
    .filter(Boolean);

  const locationVals = getMetaValues(manifest, "Main Location");
  const currentState = locationVals[0]
    ? worksIndex.find((w) => w.id === (manifest as { id: string }).id)?.state ?? ""
    : "";

  const candidates = worksIndex
    .filter((w) => w.id !== (manifest as { id: string }).id)
    .map((w) => ({ ...w, _score: score(w, currentThemes, currentState ?? "") }))
    .filter((w) => w._score > 0)
    .sort((a, b) => b._score - a._score)
    .slice(0, 6);

  if (!candidates.length) return null;

  const byTheme = candidates.filter((w) =>
    w.themes.some((t) => currentThemes.map((x) => x.toLowerCase()).includes(t.toLowerCase()))
  );
  const byState = candidates.filter(
    (w) =>
      !byTheme.includes(w) &&
      currentState &&
      w.state?.toLowerCase() === currentState.toLowerCase()
  );

  const WorkCard = ({ w }: { w: WorkEntry }) => (
    <a
      href={w.homepage}
      target="_blank"
      rel="noopener noreferrer"
      className="canopy-similar--card"
    >
      {w.thumbnail && (
        <div className="canopy-similar--thumb-wrap">
          <img src={w.thumbnail} alt="" className="canopy-similar--thumb" loading="lazy" />
        </div>
      )}
      <p className="canopy-similar--card-label">{w.label}</p>
      {w.state && <p className="canopy-similar--card-meta">{w.state}</p>}
    </a>
  );

  const Group = ({ title, items }: { title: string; items: WorkEntry[] }) => {
    if (!items.length) return null;
    return (
      <div className="canopy-similar--group">
        <h3 className="canopy-similar--group-heading">{title}</h3>
        <div className="canopy-similar--grid">
          {items.map((w) => (
            <WorkCard key={w.id} w={w} />
          ))}
        </div>
      </div>
    );
  };

  return (
    <section className="canopy-similar">
      <h2 className="canopy-similar--heading">Similar Works</h2>
      <Group
        title={`Same Theme${currentThemes.length > 1 ? "s" : ""}`}
        items={byTheme}
      />
      {currentState && (
        <Group title={`Same State — ${currentState}`} items={byState} />
      )}
    </section>
  );
}
