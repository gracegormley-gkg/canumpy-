import React from "react";
import { getMetaValue, IIIFManifest } from "./MetadataUtils";

/**
 * Renders a single metadata field as a compact label + value row.
 * Used for short fields like "Completed" and "Main Location".
 */
export default function MetaInfoItem({
  manifest,
  label,
  displayLabel,
}: {
  manifest: IIIFManifest;
  label: string;
  displayLabel?: string;
}) {
  const value = getMetaValue(manifest, label);
  if (!value) return null;

  return (
    <div className="canopy-meta-info-item">
      <span className="canopy-meta-info-item--label">{displayLabel ?? label}</span>
      <span className="canopy-meta-info-item--value">{value}</span>
    </div>
  );
}
