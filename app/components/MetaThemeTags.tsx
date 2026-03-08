import React from "react";
import { getMetaValues, IIIFManifest } from "./MetadataUtils";

/**
 * Renders the "Themes" metadata field as a list of styled pill tags.
 */
export default function MetaThemeTags({ manifest }: { manifest: IIIFManifest }) {
  const themes = getMetaValues(manifest, "Themes");
  if (!themes.length) return null;

  // A single value may be semicolon- or comma-separated — split if needed
  const allThemes = themes
    .flatMap((t) => t.split(/[;,]/).map((s) => s.trim()))
    .filter(Boolean);

  return (
    <div className="canopy-meta-themes">
      <h3 className="canopy-meta-themes--heading">Themes</h3>
      <ul className="canopy-meta-themes--list">
        {allThemes.map((theme) => (
          <li key={theme} className="canopy-meta-themes--tag">
            {theme}
          </li>
        ))}
      </ul>
    </div>
  );
}
