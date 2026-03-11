"""
Generate enriched IIIF manifests and collection.json from MongoDB export.

Sources used per work (all keyed by NUL UUID):
  - 00_collection        : base label, thumbnail, homepage
  - NUL IIIF API (live)  : real canvases with correct file set image service URLs
  - 03_summaries         : AI-generated summary (179/181 works)
  - 04_themes            : theme tags (179/181 works)
  - 06_context           : historical context + completed boolean (179/181 works)
  - 01_metadata          : main_place, key_people (179/181 works)
  - 02_geocoded_metadata : main_place, key_people, lat/lon (179/181 works, supersedes 01_metadata)

Excluded:
  - 05_quotes / PUBLIC_COMMENT: all entries are model-generated placeholders, not real data
  - ocr_output: raw OCR not suitable as display metadata
"""

import json
import re
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MONGO_FILE = REPO_ROOT / "full_doc_mongo_output_FINAL.json"
MANIFESTS_DIR = REPO_ROOT / "manifests"
COLLECTION_OUT = REPO_ROOT / "collection.json"

BASE_URL = "https://raw.githubusercontent.com/gracegormley-gkg/canumpy-/main"
NUL_API_BASE = "https://api.dc.library.northwestern.edu/api/v2/works"

MANIFESTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Load and index MongoDB documents
# ---------------------------------------------------------------------------

print("Loading MongoDB export...")
with open(MONGO_FILE) as f:
    mongo_docs = json.load(f)

collection_data = None
geocoded = {}       # uuid -> {doc_id, main_place, key_people, coordinates}
metadata_by_id = {} # uuid -> {doc_id, main_place, key_people}
summaries = {}      # uuid -> {doc_id, summary}
themes = {}         # uuid -> {doc_id, themes: []}
context = {}        # uuid -> {doc_id, context, completed}

for doc in mongo_docs:
    _id = doc["_id"]
    d = doc["data"]

    if _id == "eis-enrichment/00_collection":
        collection_data = d
    elif _id == "eis-enrichment/02_geocoded_metadata":
        # Old format: single doc keyed by UUID dict
        if isinstance(d, dict):
            for uuid, entry in d.items():
                if isinstance(entry, dict):
                    geocoded[uuid] = entry
    elif "/02_geocoded_metadata/" in _id:
        # New format: one doc per UUID
        uuid = _id.split("/")[-1]
        geocoded[uuid] = d
    elif "/01_metadata/" in _id:
        uuid = _id.split("/")[-1]
        metadata_by_id[uuid] = d
    elif "/03_summaries/" in _id:
        uuid = _id.split("/")[-1]
        summaries[uuid] = d
    elif "/04_themes/" in _id:
        uuid = _id.split("/")[-1]
        themes[uuid] = d
    elif "/06_context/" in _id:
        uuid = _id.split("/")[-1]
        context[uuid] = d

print(f"  Collection items: {len(collection_data['items'])}")
print(f"  Summaries: {len(summaries)}")
print(f"  Themes: {len(themes)}")
print(f"  Geocoded: {len(geocoded)}")
print(f"  Metadata (01): {len(metadata_by_id)}")
print(f"  Context: {len(context)}")


# ---------------------------------------------------------------------------
# Slug generation (matches existing naming convention)
# ---------------------------------------------------------------------------

MAX_SLUG_LEN = 50  # Must match Canopy's MAX_ENTRY_SLUG_LENGTH

def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:MAX_SLUG_LEN].rstrip("-")


def get_uuid(item: dict) -> str | None:
    hp = item.get("homepage", [])
    if hp:
        return hp[0]["id"].split("/")[-1]
    return None


# ---------------------------------------------------------------------------
# Fetch real canvases from NUL IIIF API (concurrent)
# ---------------------------------------------------------------------------

def fetch_nul_canvases(uuid: str) -> list | None:
    url = f"{NUL_API_BASE}/{uuid}?as=iiif"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "canumpy-manifest-builder/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                manifest = json.loads(resp.read())
                return manifest.get("items", [])
        except Exception as e:
            if attempt == 2:
                print(f"  WARN: could not fetch canvases for {uuid}: {e}")
                return None
            time.sleep(1)
    return None


print("\nFetching canvases from NUL IIIF API...")
all_uuids = [get_uuid(item) for item in collection_data["items"] if get_uuid(item)]
nul_canvases: dict[str, list] = {}

with ThreadPoolExecutor(max_workers=10) as pool:
    futures = {pool.submit(fetch_nul_canvases, uuid): uuid for uuid in all_uuids}
    done = 0
    for future in as_completed(futures):
        uuid = futures[future]
        canvases = future.result()
        if canvases:
            nul_canvases[uuid] = canvases
        done += 1
        if done % 20 == 0:
            print(f"  {done}/{len(all_uuids)} fetched...")

print(f"  Got canvases for {len(nul_canvases)}/{len(all_uuids)} works")


# ---------------------------------------------------------------------------
# Build manifests
# ---------------------------------------------------------------------------

slug_seen: dict[str, int] = {}
collection_items = []
generated = 0
skipped = 0

for item in collection_data["items"]:
    uuid = get_uuid(item)
    if not uuid:
        print(f"  SKIP (no UUID): {item.get('label')}")
        skipped += 1
        continue

    label_text = item["label"]["none"][0]
    slug_base = slugify(label_text)

    # Deduplicate slugs — mirrors Canopy's buildSlugWithSuffix logic
    if slug_base in slug_seen:
        slug_seen[slug_base] += 1
        suffix = f"-{slug_seen[slug_base]}"
        base_limit = MAX_SLUG_LEN - len(suffix)
        trimmed_base = slug_base[:base_limit].rstrip("-")
        slug = f"{trimmed_base}{suffix}"
    else:
        slug_seen[slug_base] = 0
        slug = slug_base

    manifest_url = f"{BASE_URL}/manifests/{slug}.json"

    # --- Gather enrichment data ---
    summary_text = summaries.get(uuid, {}).get("summary", "")
    theme_list = themes.get(uuid, {}).get("themes", [])
    ctx = context.get(uuid, {})

    # Location: geocoded supersedes 01_metadata
    geo_entry = geocoded.get(uuid) or metadata_by_id.get(uuid) or {}
    main_place = geo_entry.get("main_place", "")
    key_people = geo_entry.get("key_people", [])
    coords = geo_entry.get("coordinates", {}) if uuid in geocoded else {}

    # --- Build metadata array ---
    metadata = []

    if summary_text:
        metadata.append({
            "label": {"none": ["Summary"]},
            "value": {"none": [summary_text]},
        })

    if theme_list:
        metadata.append({
            "label": {"none": ["Themes"]},
            "value": {"none": ["; ".join(theme_list)]},
        })

    if main_place:
        metadata.append({
            "label": {"none": ["Main Location"]},
            "value": {"none": [main_place]},
        })

    if coords and coords.get("lat") is not None:
        metadata.append({
            "label": {"none": ["Coordinates"]},
            "value": {"none": [f"{coords['lat']}, {coords['lon']}"]},
        })

    if key_people:
        metadata.append({
            "label": {"none": ["Key People"]},
            "value": {"none": ["; ".join(key_people)]},
        })

    if ctx.get("context"):
        metadata.append({
            "label": {"none": ["Historical Context"]},
            "value": {"none": [ctx["context"]]},
        })

    if ctx.get("completed") is not None:
        metadata.append({
            "label": {"none": ["Completed"]},
            "value": {"none": ["Yes" if ctx["completed"] else "No"]},
        })

    # --- Canvases: use real NUL canvases if available ---
    canvases = nul_canvases.get(uuid, [])

    # --- Assemble manifest ---
    manifest = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": manifest_url,
        "type": "Manifest",
        "label": item["label"],
        "summary": {"none": [summary_text]} if summary_text else item.get("summary", {"none": [""]}),
        "thumbnail": item.get("thumbnail", []),
        "homepage": item.get("homepage", []),
        "metadata": metadata,
        "requiredStatement": {
            "label": {"none": ["Attribution"]},
            "value": {"none": ["Courtesy of Northwestern University Libraries"]},
        },
        "items": canvases,
    }

    out_path = MANIFESTS_DIR / f"{slug}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # --- Add stub to collection items ---
    collection_items.append({
        "id": manifest_url,
        "type": "Manifest",
        "homepage": item.get("homepage", []),
        "label": item["label"],
        "summary": {"none": [summary_text]} if summary_text else item.get("summary", {"none": [""]}),
        "thumbnail": item.get("thumbnail", []),
    })

    generated += 1

print(f"\nGenerated {generated} manifests, skipped {skipped}")


# ---------------------------------------------------------------------------
# Write collection.json
# ---------------------------------------------------------------------------

collection_out = {
    "@context": ["http://iiif.io/api/presentation/3/context.json"],
    "id": f"{BASE_URL}/collection.json",
    "type": "Collection",
    "label": {"none": ["Environmental Impact Statement Collection"]},
    "summary": collection_data["summary"],
    "items": collection_items,
    "requiredStatement": collection_data["requiredStatement"],
    "provider": collection_data["provider"],
    "logo": collection_data["logo"],
    "seeAlso": collection_data["seeAlso"],
    "homepage": collection_data["homepage"],
    "thumbnail": collection_data["thumbnail"],
}

with open(COLLECTION_OUT, "w", encoding="utf-8") as f:
    json.dump(collection_out, f, indent=2, ensure_ascii=False)

print(f"Wrote collection.json with {len(collection_items)} items")
print("Done.")
