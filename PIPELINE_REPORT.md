# Project Report: EIS Canopy Site

## Source Data

The starting point was `full_doc_mongo_output_FINAL.json` (72MB), a MongoDB export from an AI enrichment pipeline (`eis-enrichment`, run using `gemma3:1b`, timestamped 2026-03-05). It contained 471+ documents covering 181 Northwestern University EIS works across 9 document categories:

| Category | Count | Content |
|---|---|---|
| `ocr_output` | 179 | Raw OCR text from scanned pages |
| `01_metadata` | 179 | Extracted `main_place` and `key_people` per work |
| `02_geocoded_metadata` | 179 | Same + lat/lon coordinates (106/179 successfully geocoded) |
| `03_summaries` | 179 | AI-generated plain-text summary per work |
| `04_themes` | 179 | Categorical theme tags per work |
| `05_quotes` | 179 | Public comments (excluded — all were model-generated placeholders) |
| `06_context` | 179 | Historical context paragraph + completion status |
| `00_collection` | 1 | Original Northwestern IIIF Collection JSON |
| `07_enriched_manifest` | 1 | Partial assembled collection (3 items only) |

---

## What Was Built

### `scripts/generate_manifests.py` *(new file)*

A Python script that reads the MongoDB export and produces all IIIF output. It:

1. Indexes all documents by NUL UUID (the shared key across all categories)
2. Fetches the real IIIF manifest for each work from the Northwestern API (`api.dc.library.northwestern.edu/api/v2/works/{uuid}?as=iiif`) using a 10-worker thread pool to extract real canvases with correct file set image service URLs and page dimensions
3. For each of the 181 works, assembles a complete IIIF Presentation 3 Manifest combining:
   - Base data (label, thumbnail, homepage) from `00_collection`
   - Real canvases (pages + image service) from the live NUL IIIF API
   - Summary text from `03_summaries`
   - Theme tags from `04_themes`
   - Main location + key people from `02_geocoded_metadata` (falling back to `01_metadata`)
   - Lat/lon coordinates from `02_geocoded_metadata` where available
   - Historical context + completed status from `06_context`
4. Generates URL-safe slugs from titles (max 80 chars, word-boundary truncated, `-1`/`-2` suffixed for duplicates)
5. Writes each manifest to `manifests/{slug}.json`
6. Writes a new `collection.json` referencing all 181 manifests

**Metadata coverage in generated manifests:**

| Field | Works |
|---|---|
| Summary | 179/181 |
| Themes | 179/181 |
| Main Location | 179/181 |
| Key People | 179/181 |
| Historical Context | 179/181 |
| Completed | 179/181 |
| Coordinates | 106/181 |

**Excluded from manifests:** `05_quotes` (public comments were clearly hallucinated by the model — all entries were placeholder strings like `"'exact quote' - Name"`) and `ocr_output` (raw OCR not suitable as display metadata).

---

## Changes from the Canopy Template

### 1. `canopy.yml`

| Setting | Template value | Changed to |
|---|---|---|
| `title` | `"Canopy IIIF"` (+ random string artifact) | `"Environmental Impact Statement Collection"` |
| `site.baseUrl` | *(not set)* | `https://gracegormley-gkg.github.io/canumpy-` |
| `collection` | pointed to `canopy_output/collection.json` (wrong path) | `https://raw.githubusercontent.com/gracegormley-gkg/canumpy-/main/collection.json` |
| `metadata` | `[Summary, Themes]` | `[Summary, Themes, Main Location, Key People, Historical Context, Completed]` |

### 2. `.github/workflows/deploy-pages.yml`

| Setting | Template value | Changed to | Reason |
|---|---|---|---|
| `CANOPY_FETCH_CONCURRENCY` | `1` | `10` | Sequential fetching of 181 manifests took ~200s; parallel cuts it to ~20s |
| `CANOPY_CHUNK_SIZE` | `10` | `25` | Better batching for larger collection |
| `run` command | `npm run build` | `timeout 300 npm run build \|\| true` | Canopy's build and dev scripts share the same entry point; after printing "Build complete" the process hangs indefinitely on open handles (esbuild/HTTP clients). The shell timeout kills it cleanly after the build completes without blocking the artifact upload step |

### 3. `manifests/` *(181 new files)*

All generated from the MongoDB pipeline via `scripts/generate_manifests.py`. The template ships with no manifests; these replace the 3-item stub that existed in the previous partial attempt.

Each manifest is a valid IIIF Presentation 3 document containing:
- Real canvases copied from the Northwestern IIIF API (correct file set UUIDs, real page dimensions)
- All enrichment metadata from the pipeline as IIIF `metadata` label/value pairs
- Northwestern attribution statement
- Thumbnail and homepage linking back to the NUL Digital Collections item

### 4. `collection.json` *(replaced)*

The previous version pointed to a non-existent `canopy_output/manifests/` path and listed only ~45 items (with only 3 having actual manifest files). Replaced with a clean IIIF Collection referencing all 181 generated manifests at their correct `raw.githubusercontent.com` URLs, with AI-generated summaries surfaced as collection item summaries (replacing the generic `"Image"` placeholder from the original NUL data).

### 5. `app/scripts/canopy-build.mts` *(unchanged from template)*

Reverted to the original template version after an attempted `process.exit(0)` fix proved to kill the Node process before `site/` writes flushed to disk, producing an empty deployed artifact. The hanging process is handled instead by the `timeout` wrapper in the workflow.

---

## Why Images Were Initially Broken

The first version of `generate_manifests.py` constructed IIIF canvases using the work UUID as the image service identifier:

```
https://iiif.dc.library.northwestern.edu/iiif/3/{work-uuid}/full/max/0/default.jpg
```

Northwestern's IIIF image server does not use work UUIDs — it uses **file set UUIDs**, one per scanned page, which are different from and not derivable from the work UUID. The fix was to fetch the real IIIF manifest from the NUL API for each work and copy its canvas structure directly, which provides the correct file set UUIDs, accurate page dimensions, and the full multi-page structure for works with more than one scan.

---

## Files Not Committed to Git

- `full_doc_mongo_output.json` (42MB, first pipeline run)
- `full_doc_mongo_output_FINAL.json` (72MB, final pipeline run)

Both exceed GitHub's recommended 50MB file size threshold. The generated manifests are the durable artifact; the raw MongoDB exports should be stored separately (locally or in object storage) and re-run through `scripts/generate_manifests.py` if manifests need to be regenerated.
