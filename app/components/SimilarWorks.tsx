import React from "react";
import fs from "fs";
import path from "path";
import { getMetaValues, IIIFManifest } from "./MetadataUtils";

type WorkEntry = {
  slug: string;
  id: string;
  label: string;
  thumbnail: string;
  themes: string[];
  state: string | null;
  completed: string;
};

const US_STATES = [
  "Alabama","Alaska","Arizona","Arkansas","California","Colorado",
  "Connecticut","Delaware","Florida","Georgia","Hawaii","Idaho",
  "Illinois","Indiana","Iowa","Kansas","Kentucky","Louisiana","Maine",
  "Maryland","Massachusetts","Michigan","Minnesota","Mississippi",
  "Missouri","Montana","Nebraska","Nevada","New Hampshire","New Jersey",
  "New Mexico","New York","North Carolina","North Dakota","Ohio",
  "Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina",
  "South Dakota","Tennessee","Texas","Utah","Vermont","Virginia",
  "Washington","West Virginia","Wisconsin","Wyoming","District of Columbia",
];

function extractState(location: string): string {
  for (const state of US_STATES) {
    if (location.toLowerCase().includes(state.toLowerCase())) return state;
  }
  return "";
}

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
  let index: WorkEntry[] = [];
  try {
    const indexPath = path.resolve(process.cwd(), "assets/works-index.json");
    index = JSON.parse(fs.readFileSync(indexPath, "utf-8"));
  } catch {
    return null;
  }

  const rawThemes = getMetaValues(manifest, "Themes");
  const currentThemes = rawThemes
    .flatMap((t) => t.split(";").map((s) => s.trim()))
    .filter(Boolean);

  const locationVals = getMetaValues(manifest, "Main Location");
  const currentState = locationVals.length ? extractState(locationVals[0]) : "";

  const candidates = index
    .filter((w) => w.id !== (manifest as { id: string }).id)
    .map((w) => ({ ...w, _score: score(w, currentThemes, currentState) }))
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
    <a href={`/canumpy-/works/${w.slug}`} className="canopy-similar--card">
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
