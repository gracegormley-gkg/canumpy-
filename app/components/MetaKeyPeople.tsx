import React from "react";
import { getMetaValues, IIIFManifest } from "./MetadataUtils";

/**
 * Renders the "Key People" metadata field as a structured list.
 * Values may be semicolon-separated names in a single string.
 */
export default function MetaKeyPeople({ manifest }: { manifest: IIIFManifest }) {
  const raw = getMetaValues(manifest, "Key People");
  if (!raw.length) return null;

  const people = raw
    .flatMap((v) => v.split(";").map((s) => s.trim()))
    .filter(Boolean);

  return (
    <section className="canopy-meta-key-people">
      <h2 className="canopy-meta-key-people--heading">Key People</h2>
      <ul className="canopy-meta-key-people--list">
        {people.map((person) => (
          <li key={person} className="canopy-meta-key-people--item">
            {person}
          </li>
        ))}
      </ul>
    </section>
  );
}
