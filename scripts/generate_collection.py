"""
Generate IIIF Collection + Manifests from eis_results_v4.json

Output:
  output/collection-eis-v3.json
  output/manifests/<slug>.json  (181 files)

Metadata fields (same labels as v2 for backward compatibility):
  Summary, Themes, Main Location, Key People, Historical Context,
  Completed, Year, Bureau
  + NEW: Notable Quotes

Usage:
  python generate_collection.py [--base-url https://raw.githubusercontent.com/YOUR/REPO/main]
"""

import json
import re
import sys
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://raw.githubusercontent.com/gracegormley-gkg/canumpy-/main"

base_url = DEFAULT_BASE_URL
if "--base-url" in sys.argv:
    idx = sys.argv.index("--base-url")
    base_url = sys.argv[idx + 1]

INPUT_FILE = Path(__file__).parent / "eis_results_v4.json"
OUTPUT_DIR = Path(__file__).parent / "output"
MANIFESTS_DIR = OUTPUT_DIR / "manifests"
COLLECTION_FILE = OUTPUT_DIR / "collection-eis-v3.json"
INDEX_FILE = OUTPUT_DIR / "eis-index.json"

US_STATES = [
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut",
    "Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa",
    "Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan",
    "Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada",
    "New Hampshire","New Jersey","New Mexico","New York","North Carolina",
    "North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island",
    "South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont",
    "Virginia","Washington","West Virginia","Wisconsin","Wyoming",
    "District of Columbia","Washington, D.C.",
]

def extract_state(location: str) -> str:
    if not location:
        return "Unknown"
    for state in sorted(US_STATES, key=len, reverse=True):
        pattern = r"\b" + re.escape(state) + r"\b"
        if re.search(pattern, location, re.IGNORECASE):
            if state in ("Washington, D.C.", "District of Columbia"):
                return "Washington, D.C."
            return state
    return "Federal / International"

OUTPUT_DIR.mkdir(exist_ok=True)
MANIFESTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str, max_len: int = 50) -> str:
    """Convert title to URL-safe slug, truncated to max_len chars."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def iiif_label(text: str) -> dict:
    return {"none": [text]}


def iiif_value(values: list) -> dict:
    return {"none": [str(v) for v in values if v]}


def meta_field(label: str, values: list) -> dict | None:
    clean = [str(v).strip() for v in values if str(v).strip()]
    if not clean:
        return None
    return {
        "label": iiif_label(label),
        "value": iiif_value(clean),
    }


def build_canvas(work_id: str, index: int, fs: dict) -> dict:
    """Build a IIIF Canvas from a file_set entry."""
    fs_id = fs["id"]
    image_service = fs.get("representative_image_url", "")
    width = fs.get("width") or 2000
    height = fs.get("height") or 2800
    label = fs.get("label") or str(index)

    canvas_id = f"https://api.dc.library.northwestern.edu/api/v2/works/{work_id}?as=iiif/canvas/{index}"
    anno_page_id = f"{canvas_id}/annotation-page"
    anno_id = f"{canvas_id}/annotation/{index}"

    thumbnail = []
    if image_service:
        thumbnail = [{
            "id": f"{image_service}/full/!300,300/0/default.jpg",
            "type": "Image",
            "format": "image/jpeg",
            "height": 300,
            "width": 300,
            "service": [{
                "@id": image_service,
                "@type": "ImageService2",
                "profile": "http://iiif.io/api/image/2/level2.json",
            }],
        }]

    body = {
        "id": f"{image_service}/full/600,/0/default.jpg" if image_service else "",
        "type": "Image",
        "format": "image/jpeg",
        "height": height,
        "width": width,
    }
    if image_service:
        body["service"] = [{
            "@id": image_service,
            "@type": "ImageService2",
            "profile": "http://iiif.io/api/image/2/level2.json",
        }]

    return {
        "id": canvas_id,
        "type": "Canvas",
        "height": height,
        "width": width,
        "label": iiif_label(str(label)),
        "thumbnail": thumbnail,
        "items": [{
            "id": anno_page_id,
            "type": "AnnotationPage",
            "items": [{
                "id": anno_id,
                "type": "Annotation",
                "motivation": "painting",
                "target": canvas_id,
                "body": body,
            }],
        }],
    }


def format_quotes(quotes: list) -> list:
    """Format notable_quotes list into display strings."""
    out = []
    for q in quotes:
        quote_text = q.get("quote", "").strip()
        attribution = q.get("attribution", "").strip()
        if quote_text and attribution:
            out.append(f'"{quote_text}" — {attribution}')
        elif quote_text:
            out.append(f'"{quote_text}"')
    return out


def build_manifest(record: dict, slug: str) -> dict:
    nul = record["nul_metadata"]
    enr = record["enrichments"]
    work_id = nul["id"]
    manifest_url = f"{base_url}/manifests/{slug}.json"

    # --- Metadata fields (backward-compatible labels) ---
    metadata = []

    # Summary
    f = meta_field("Summary", [enr.get("summary", "")])
    if f: metadata.append(f)

    # Themes (array)
    themes = enr.get("theme", [])
    if isinstance(themes, str):
        themes = [themes]
    f = meta_field("Themes", themes)
    if f: metadata.append(f)

    # Main Location
    f = meta_field("Main Location", [enr.get("location", "")])
    if f: metadata.append(f)

    # Key People and Groups (array → stored as separate values)
    people = enr.get("key_people_and_groups", [])
    if isinstance(people, str):
        people = [people]
    f = meta_field("Key People and Groups", people)
    if f: metadata.append(f)

    # Historical Context
    f = meta_field("Historical Context", [enr.get("external_context", "")])
    if f: metadata.append(f)

    # Completed (mapped to display values for color coding)
    raw_status = enr.get("project_status", "")
    status_map = {
        "Completed": "Complete",
        "Incomplete": "Incomplete",
        "Never started": "Not Started",
        "unknown": "Not Started",
    }
    status = status_map.get(raw_status, raw_status)
    f = meta_field("Completed", [status])
    if f: metadata.append(f)

    # Year
    years = nul.get("date_created", [])
    f = meta_field("Year", years[:1])
    if f: metadata.append(f)

    # Bureau (contributor label)
    contributors = nul.get("contributor", [])
    bureau_labels = [c["label"] for c in contributors if c.get("label")]
    f = meta_field("Bureau", bureau_labels)
    if f: metadata.append(f)

    # Contributor (NUL field — all contributor display names)
    f = meta_field("Contributor", bureau_labels)
    if f: metadata.append(f)

    # Notable Quotes (NEW)
    # Suppress quotes that mention Havasupai if the title doesn't also mention it
    quotes = enr.get("notable_quotes", [])
    title_lower = nul.get("title", "").lower()
    if "havasupai" not in title_lower:
        quotes = [q for q in quotes if "havasupai" not in q.get("quote", "").lower()]
    formatted_quotes = format_quotes(quotes)
    f = meta_field("Notable Quotes", formatted_quotes)
    if f: metadata.append(f)

    # --- Thumbnail ---
    thumbnail_url = nul.get("thumbnail", "")
    thumbnail = []
    if thumbnail_url:
        thumbnail = [{
            "id": thumbnail_url,
            "type": "Image",
            "format": "image/jpeg",
        }]

    # --- Homepage ---
    dc_url = f"https://dc.library.northwestern.edu/items/{work_id}"
    homepage = [{
        "id": dc_url,
        "type": "Text",
        "format": "text/html",
        "label": iiif_label(nul.get("title", "")),
    }]

    # --- Canvases ---
    file_sets = [
        fs for fs in nul.get("file_sets", [])
        if fs.get("role") == "Access" and fs.get("mime_type", "").startswith("image/")
    ]
    # Sort by rank to maintain page order
    file_sets.sort(key=lambda fs: fs.get("rank", 0))
    canvases = [build_canvas(work_id, i, fs) for i, fs in enumerate(file_sets)]

    title = nul.get("title", "Untitled")

    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": manifest_url,
        "type": "Manifest",
        "label": iiif_label(title),
        "summary": iiif_label(enr.get("summary", "")),
        "thumbnail": thumbnail,
        "homepage": homepage,
        "metadata": metadata,
        "requiredStatement": {
            "label": iiif_label("Attribution"),
            "value": iiif_label(
                nul.get("terms_of_use", "Northwestern University Libraries")
            ),
        },
        "items": canvases,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print(f"Loading {INPUT_FILE}...")
with open(INPUT_FILE) as f:
    data = json.load(f)

print(f"Sorting {len(data)} records by year...")
data.sort(key=lambda r: int((r["nul_metadata"].get("date_created") or ["0"])[0] or 0))

print(f"Generating {len(data)} manifests...")

collection_items = []
index_items = []
seen_slugs: dict[str, int] = {}

for i, record in enumerate(data):
    nul = record["nul_metadata"]
    title = nul.get("title", f"record-{i}")
    base_slug = slugify(title)

    # Deduplicate slugs
    if base_slug in seen_slugs:
        seen_slugs[base_slug] += 1
        slug = f"{base_slug}-{seen_slugs[base_slug]}"
    else:
        seen_slugs[base_slug] = 0
        slug = base_slug

    manifest = build_manifest(record, slug)
    manifest_path = MANIFESTS_DIR / f"{slug}.json"

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Collection item (lightweight)
    enr = record["enrichments"]
    thumbnail_url = nul.get("thumbnail", "")
    item = {
        "id": f"{base_url}/manifests/{slug}.json",
        "type": "Manifest",
        "homepage": [{
            "id": f"https://dc.library.northwestern.edu/items/{nul['id']}",
            "type": "Text",
            "format": "text/html",
            "label": iiif_label(nul.get("title", "")),
        }],
        "label": iiif_label(nul.get("title", "")),
        "summary": iiif_label(enr.get("summary", "")),
    }
    if thumbnail_url:
        item["thumbnail"] = [{"id": thumbnail_url, "type": "Image", "format": "image/jpeg"}]

    collection_items.append(item)

    # Index entry for browse page
    enr_themes = enr.get("theme", [])
    if isinstance(enr_themes, str):
        enr_themes = [enr_themes]
    raw_status = enr.get("project_status", "")
    status_map = {"Completed": "Complete", "Incomplete": "Incomplete",
                  "Never started": "Not Started", "unknown": "Not Started"}
    index_items.append({
        "title": nul.get("title", "Untitled"),
        "thumbnail": thumbnail_url,
        "year": (nul.get("date_created", []) or [""])[ 0] or "",
        "state": extract_state(enr.get("location", "")),
        "themes": [t for t in enr_themes if t],
        "status": status_map.get(raw_status, raw_status or "Unknown"),
        "manifestUrl": f"{base_url}/manifests/{slug}.json",
    })

    if (i + 1) % 25 == 0:
        print(f"  {i + 1}/{len(data)} done...")

# Build collection
collection = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": f"{base_url}/collection-eis-v3.json",
    "type": "Collection",
    "label": iiif_label("EIS Archives"),
    "summary": iiif_label(
        "Environmental Impact Statement Collection — Northwestern University Libraries"
    ),
    "items": collection_items,
    "requiredStatement": {
        "label": iiif_label("Attribution"),
        "value": iiif_label("Northwestern University Libraries"),
    },
    "provider": [{
        "id": "https://www.library.northwestern.edu/",
        "type": "Agent",
        "label": iiif_label("Northwestern University Libraries"),
        "homepage": [{"id": "https://www.library.northwestern.edu/", "type": "Text", "format": "text/html", "label": iiif_label("Northwestern University Libraries")}],
    }],
}

print(f"Writing collection to {COLLECTION_FILE}...")
with open(COLLECTION_FILE, "w") as f:
    json.dump(collection, f, ensure_ascii=False, indent=2)

print(f"Writing browse index to {INDEX_FILE}...")
with open(INDEX_FILE, "w") as f:
    json.dump(index_items, f, ensure_ascii=False, indent=2)

print(f"\nDone!")
print(f"  Collection: {COLLECTION_FILE}")
print(f"  Manifests:  {MANIFESTS_DIR}/ ({len(data)} files)")
print(f"  Index:      {INDEX_FILE}")
print(f"\nNext: upload output/ to GitHub and update canopy.yml collection URL to:")
print(f"  {base_url}/collection-eis-v3.json")
