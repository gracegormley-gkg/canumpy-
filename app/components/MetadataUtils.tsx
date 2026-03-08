import React from "react";

export type IIIFManifest = {
  metadata?: Array<{
    label: Record<string, string[]>;
    value: Record<string, string[]>;
  }>;
  [key: string]: unknown;
};

/**
 * Extract all values for a given metadata label from a IIIF manifest.
 * Checks every language key in the label object.
 */
export function getMetaValues(manifest: IIIFManifest, fieldLabel: string): string[] {
  if (!manifest?.metadata) return [];
  for (const entry of manifest.metadata) {
    const labelValues = Object.values(entry.label).flat();
    if (labelValues.some((v) => v.toLowerCase() === fieldLabel.toLowerCase())) {
      return Object.values(entry.value).flat();
    }
  }
  return [];
}

/**
 * Returns the first value for a given metadata label, or undefined.
 */
export function getMetaValue(manifest: IIIFManifest, fieldLabel: string): string | undefined {
  return getMetaValues(manifest, fieldLabel)[0];
}
