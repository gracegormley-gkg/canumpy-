# Project Report: EIS Canopy Site

## Overview

This site presents 181 Environmental Impact Statement (EIS) documents from Northwestern University Libraries, enriched with AI-generated metadata and published as a browsable IIIF collection via the Canopy framework.

---

## Pipeline Summary

The data pipeline runs in two stages:

```
docs_with_digits.json  +  NUL API
         │
         ▼
  scripts/pipeline.py          ← Stage 1: OpenAI enrichment
         │
         ▼
   eis_results_v4.json
         │
         ▼
  scripts/generate_collection.py  ← Stage 2: IIIF generation
         │
         ▼
  collection-eis-v3.json  +  manifests/*.json
         │
         ▼
  pushed to GitHub → EIS-Final site pulls at build time
```

---

## Stage 1: Enrichment (`scripts/pipeline.py`)

### Inputs
- **`docs_with_digits.json`** — pre-existing OCR text for each EIS document, keyed by accession number (e.g. `P0491_35556036806768`). Not committed to git due to size.
- **NUL Digital Collections API** (`api.dc.library.northwestern.edu/api/v2`) — fetches catalog metadata for all 181 works in collection `f2fc1bd8-c37f-4486-b28a-509f0e0362e1`.

### Model
- **OpenAI GPT-4o-mini** — all LLM calls
- **Nominatim (OpenStreetMap)** — geocoding

### Matching
Each NUL work is matched to its OCR text via accession number. Three fallback strategies handle format variations (e.g. bare barcode `35556036806768` matching `P0491_35556036806768`).

### Enrichment Steps

| Step | Output field | Description |
|------|-------------|-------------|
| 1 | `summary` | ~100-word plain-language summary of the proposal, location, and community impact |
| 2 | `location` | Primary geographic area (city/county/state or corridor endpoints) |
| 3 | `key_people_and_groups` | 3–5 agencies, companies, or named individuals prominently mentioned |
| 4 | `notable_quotes` | 0–3 verbatim quotes that are emotionally resonant or historically revealing (high bar — many documents return none) |
| 5 | `coordinates` | Lat/lon from Nominatim geocoding of `location` |
| 6 | `theme` / `subthemes` | Classified into 1–2 of 10 themes (see taxonomy below) |
| 7 | `external_context` | 2–4 sentence historical backstory: why the project was proposed, public response, and what ultimately happened |
| 8 | `project_status` | One of: `Completed`, `Incomplete`, `Never started`, `unknown` |

### Theme Taxonomy

| Theme | Subthemes |
|-------|-----------|
| Transportation Infrastructure | Mobility Networks and Connectivity; Infrastructure Impacts on Landscapes |
| Energy Systems | Energy Extraction and Production; Energy Distribution and Consumption |
| Wildlife and Natural Areas | Habitat Conservation and Biodiversity; Human–Wildlife Interactions |
| Water Systems | Water Infrastructure and Management; Water Scarcity and Environmental Change |
| Urban Development | Urban Expansion and Land Use Change; Housing, Planning, and Built Environment |
| Industrial Production and Materials | Resource Extraction and Material Flows; Industrial Manufacturing and Pollution |
| Climate and Weather Modification | Climate Engineering and Intervention; Adaptation to Climate Variability |
| Governance and Institutional Control | Environmental Regulation and Policy; Institutional Power and Resource Management |
| Place Based Development Conflicts | Community Resistance and Activism; Land Rights and Displacement |
| Indigenous Narratives and Sovereignty | Indigenous Knowledge and Environmental Stewardship; Sovereignty, Rights, and Self-Determination |

### Output
`eis_results_v4.json` — 181 records, each with:
```json
{
  "nul_metadata": { "id", "title", "date_created", "contributor", "file_sets", "thumbnail", ... },
  "enrichments":  { "summary", "location", "coordinates", "key_people_and_groups",
                    "notable_quotes", "theme", "subthemes", "external_context", "project_status" },
  "processing":   { "ocr_source", "ocr_chars", "llm_model", "processed_at" }
}
```

Pipeline supports resuming — already-processed work IDs are skipped on re-run. Results are saved to disk every 10 documents as a checkpoint.

---

## Stage 2: IIIF Generation (`scripts/generate_collection.py`)

### Input
`eis_results_v4.json`

### What it does
1. Sorts records by year
2. Generates a URL-safe slug from each title (max 50 chars, deduplicated with `-2`, `-3` suffixes)
3. Builds a IIIF Presentation 3 Manifest per work combining:
   - NUL catalog metadata (title, date, contributor, thumbnail, homepage)
   - Canvases from `file_sets` in the NUL metadata (correct file set UUIDs and image service URLs)
   - All enrichment fields as IIIF `metadata` label/value pairs
4. Writes `output/manifests/<slug>.json` for each work
5. Writes `output/collection-eis-v3.json` — a IIIF Collection referencing all 181 manifests
6. Writes `output/eis-index.json` — lightweight index used by the browse/filter UI

### Metadata fields in each manifest

| IIIF Label | Source |
|-----------|--------|
| Summary | `enrichments.summary` |
| Themes | `enrichments.theme` |
| Main Location | `enrichments.location` |
| Key People and Groups | `enrichments.key_people_and_groups` |
| Historical Context | `enrichments.external_context` |
| Completed | `enrichments.project_status` (mapped to Complete / Incomplete / Not Started) |
| Year | `nul_metadata.date_created[0]` |
| Bureau | `nul_metadata.contributor[].label` |
| Notable Quotes | `enrichments.notable_quotes` (formatted as `"quote" — attribution`) |

**Note:** Quotes mentioning "Havasupai" are suppressed unless the document title also references Havasupai.

### Coverage (181 works total)

| Field | Works with data |
|-------|----------------|
| Summary | 181/181 |
| Themes | 181/181 |
| Main Location | 181/181 |
| Key People and Groups | 181/181 |
| Historical Context | 181/181 |
| Completed | 181/181 |
| Coordinates | ~106/181 (Nominatim match rate) |
| Notable Quotes | subset — only where genuinely meaningful quotes were found |

---

## How the Site Consumes This Data

`EIS-Final/canopy.yml` points to:
```
https://raw.githubusercontent.com/gracegormley-gkg/canumpy-/main/collection-eis-v2.json
```

At build time, Canopy fetches that collection, resolves each manifest URL, and generates the static site. To update the site with a new pipeline run:

1. Run `scripts/pipeline.py` → produces `eis_results_v4.json`
2. Run `scripts/generate_collection.py` → produces `output/collection-eis-v3.json` + `output/manifests/*.json`
3. Copy outputs into this repo:
   ```bash
   cp output/collection-eis-v3.json ./collection-eis-v3.json
   cp output/manifests/*.json ./manifests/
   ```
4. Update `EIS-Final/canopy.yml` collection URL to `collection-eis-v3.json` if switching versions
5. Commit and push — GitHub Actions redeploys automatically

---

## Files Not Committed to Git

| File | Reason |
|------|--------|
| `docs_with_digits.json` | Pre-OCR source text — large, store locally |
| `eis_results_v4.json` | Pipeline output — large, regenerable from source |
| `full_doc_mongo_output*.json` | Earlier pipeline run artifacts — superseded |

These are excluded via `.gitignore`. The manifests in `manifests/` are the durable artifact.

---

## Requirements

```
pip install openai requests geopy tenacity
export OPENAI_API_KEY="sk-..."
python scripts/pipeline.py
python scripts/generate_collection.py
```
