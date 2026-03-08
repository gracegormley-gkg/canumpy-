import React from "react";
import { getMetaValue, IIIFManifest } from "./MetadataUtils";

/**
 * Renders the "Historical Context" field as a distinct full-width section
 * with a prominent heading — analogous to the "What actually happened?" block
 * in the mock-up.
 */
export default function MetaHistoricalContext({ manifest }: { manifest: IIIFManifest }) {
  const text = getMetaValue(manifest, "Historical Context");
  if (!text) return null;

  return (
    <section className="canopy-meta-historical">
      <h2 className="canopy-meta-historical--heading">Historical Context</h2>
      <p className="canopy-meta-historical--body">{text}</p>
    </section>
  );
}
