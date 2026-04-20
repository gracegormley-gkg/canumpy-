"""
EIS Document Processing Pipeline
=================================
Processes Environmental Impact Statements from Northwestern University's
Digital Collections. Matches pre-existing OCR text (docs_with_digits.json)
to NUL catalog metadata via the `identifier` subfield, then enriches each
document with LLM-extracted summary, geocoded location, theme classification,
and historical context.

Requirements:
    pip install openai requests geopy tenacity

Usage:
    1. Set your OpenAI API key:  export OPENAI_API_KEY="sk-..."
    2. Run:  python pipeline.py
"""

import os
import json
import time
import logging
import requests
from typing import Optional
from openai import OpenAI
from geopy.geocoders import Nominatim
from tenacity import retry, stop_after_attempt, wait_exponential

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

COLLECTION_ID = "f2fc1bd8-c37f-4486-b28a-509f0e0362e1"
API_BASE      = "https://api.dc.library.northwestern.edu/api/v2"

TEXT_FILE  = "docs_with_digits.json"
OUTPUT_FILE = "eis_results_v2.json"
BATCH_SIZE  = 10   # save to disk every N documents

# How much of each document to feed the LLM.
# OCR text averages ~2500 chars/page; taking the front and back
# lets us capture title/summary pages AND the bibliography/quotes section.
FIRST_N_PAGES = 10   # pages from the start
LAST_N_PAGES  = 15   # pages from the end (extra tail for citations/quotes)
CHARS_PER_PAGE = 2500

OCR_MODEL = "gpt-4o-mini"
LLM_MODEL = "gpt-4o-mini"

# ---------------------------------------------------------------------------
# THEME TAXONOMY
# ---------------------------------------------------------------------------

THEMES = {
    "Transportation Infrastructure": {
        "subthemes": [
            "Mobility Networks and Connectivity",
            "Infrastructure Impacts on Landscapes"
        ]
    },
    "Energy Systems": {
        "subthemes": [
            "Energy Extraction and Production",
            "Energy Distribution and Consumption"
        ]
    },
    "Wildlife and Natural Areas": {
        "subthemes": [
            "Habitat Conservation and Biodiversity",
            "Human–Wildlife Interactions"
        ]
    },
    "Water Systems": {
        "subthemes": [
            "Water Infrastructure and Management",
            "Water Scarcity and Environmental Change"
        ]
    },
    "Urban Development": {
        "subthemes": [
            "Urban Expansion and Land Use Change",
            "Housing, Planning, and Built Environment"
        ]
    },
    "Industrial Production and Materials": {
        "subthemes": [
            "Resource Extraction and Material Flows",
            "Industrial Manufacturing and Pollution"
        ]
    },
    "Climate and Weather Modification": {
        "subthemes": [
            "Climate Engineering and Intervention",
            "Adaptation to Climate Variability"
        ]
    },
    "Governance and Institutional Control": {
        "subthemes": [
            "Environmental Regulation and Policy",
            "Institutional Power and Resource Management"
        ]
    },
    "Place Based Development Conflicts": {
        "subthemes": [
            "Community Resistance and Activism",
            "Land Rights and Displacement"
        ]
    },
    "Indigenous Narratives and Sovereignty": {
        "subthemes": [
            "Indigenous Knowledge and Environmental Stewardship",
            "Sovereignty, Rights, and Self-Determination"
        ]
    }
}

# ---------------------------------------------------------------------------
# NUL METADATA FIELDS TO PRESERVE
# ---------------------------------------------------------------------------

NUL_FIELDS_TO_KEEP = [
    "id", "title", "alternate_title", "description", "abstract",
    "date_created", "date_created_edtf", "create_date", "modified_date",
    "work_type", "visibility", "published",
    "rights_statement", "terms_of_use", "license",
    "collection", "contributor", "creator", "subject", "genre", "language",
    "publisher", "source", "related_url", "identifier",
    "accession_number", "catalog_key", "library_unit",
    "physical_description_size", "physical_description_material",
    "box_number", "box_name", "folder_number", "folder_name", "series",
    "style_period", "technique", "scope_and_contents", "table_of_contents",
    "notes", "caption", "provenance", "keywords", "nav_place",
    "iiif_manifest", "thumbnail", "representative_file_set", "file_sets",
    "batch_ids", "project", "ingest_project", "ingest_sheet",
]

# ---------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

client     = OpenAI()
geolocator = Nominatim(user_agent="eis_pipeline_v1")

# Load pre-existing OCR text
with open(TEXT_FILE, "r", encoding="utf-8") as f:
    DOCS: dict[str, str] = json.load(f)

log.info(f"Loaded {len(DOCS)} pre-OCR'd documents from {TEXT_FILE}")


# ---------------------------------------------------------------------------
# STEP 1: Fetch NUL works + extract metadata
# ---------------------------------------------------------------------------

def fetch_collection_works() -> list[dict]:
    """Fetch all works in the collection from the NUL API (GET search)."""
    works = []
    page = 1
    page_size = 25  # NUL API hard limit

    while True:
        log.info(f"Fetching works from NUL API (page={page})...")
        resp = requests.get(
            f"{API_BASE}/search",
            params={
                "query": f"collection.id:{COLLECTION_ID}",
                "size":  page_size,
                "page":  page,
            },
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("data", [])
        if not hits:
            break

        works.extend(hits)

        pagination = data.get("pagination", {})
        if not pagination.get("next_url"):
            break

        page += 1
        time.sleep(0.5)

    log.info(f"Found {len(works)} works in NUL collection.")
    return works


def extract_nul_metadata(raw_work: dict) -> dict:
    """Pull the NUL fields we want to preserve."""
    preserved = {}
    for field in NUL_FIELDS_TO_KEEP:
        if field in raw_work:
            preserved[field] = raw_work[field]

    work_id = raw_work.get("id", "")
    preserved["source_url"] = f"https://dc.library.northwestern.edu/items/{work_id}"
    preserved["api_link"]   = f"{API_BASE}/works/{work_id}"
    if "iiif_manifest" not in preserved:
        preserved["iiif_manifest"] = f"{API_BASE}/works/{work_id}?as=iiif"

    return preserved


# ---------------------------------------------------------------------------
# STEP 2: Match NUL work → pre-existing OCR text via identifier subfield
# ---------------------------------------------------------------------------

def _identifier_strings(raw_work: dict) -> list[str]:
    """
    Extract every string value buried inside the `identifier` field.

    The NUL API returns `identifier` in several shapes:
      - a list of dicts:  [{"id": "P0491_...", "source": "..."}, ...]
      - a list of strings: ["P0491_...", ...]
      - a plain string:   "P0491_..."
      - absent / None

    We flatten everything to a list of strings for easy matching.
    """
    raw = raw_work.get("identifier")
    if not raw:
        return []

    candidates: list[str] = []

    def _harvest(obj):
        if isinstance(obj, str):
            candidates.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _harvest(v)
        elif isinstance(obj, list):
            for item in obj:
                _harvest(item)

    _harvest(raw)
    return candidates


def find_ocr_text(raw_work: dict) -> Optional[tuple[str, str]]:
    """
    Try to find pre-existing OCR text in DOCS for this NUL work.

    Match strategy (in order):
      1. accession_number is an exact key in DOCS (case-insensitive)
         e.g. NUL "P0491_35556036806768" == JSON key "P0491_35556036806768"
      2. Any value in the identifier array matches a DOCS key exactly
      3. Any value in the identifier array (the bare barcode) is a substring
         of a DOCS key — handles "35556036806768" matching "P0491_35556036806768"

    Returns (doc_id, ocr_text) or None if no match found.
    """
    # Strategy 1 — accession_number direct match (most reliable)
    accession = raw_work.get("accession_number", "")
    if accession:
        if accession in DOCS:
            return accession, DOCS[accession]
        # case-insensitive fallback
        accession_lower = accession.lower()
        for doc_id in DOCS:
            if doc_id.lower() == accession_lower:
                return doc_id, DOCS[doc_id]

    # Strategy 2 — exact match on any identifier string
    id_strings = _identifier_strings(raw_work)
    for id_str in id_strings:
        if id_str in DOCS:
            return id_str, DOCS[id_str]

    # Strategy 3 — identifier value is a substring of a DOCS key
    #              (bare barcode "35556036806768" inside "P0491_35556036806768")
    for id_str in id_strings:
        if not id_str:
            continue
        for doc_id in DOCS:
            if id_str in doc_id:
                return doc_id, DOCS[doc_id]

    return None


# ---------------------------------------------------------------------------
# STEP 3: LLM extraction — Summary, Location, Key People
# ---------------------------------------------------------------------------

def select_text_window(ocr_text: str) -> str:
    """
    Take the first FIRST_N_PAGES and last LAST_N_PAGES worth of OCR text.
    The extra tail captures bibliography and quoted sources that appear at
    the end of EIS documents.
    """
    head_chars = FIRST_N_PAGES * CHARS_PER_PAGE
    tail_chars = LAST_N_PAGES  * CHARS_PER_PAGE
    total      = head_chars + tail_chars

    if len(ocr_text) <= total:
        return ocr_text

    head = ocr_text[:head_chars]
    tail = ocr_text[-tail_chars:]
    return head + "\n\n[...MIDDLE SECTION TRUNCATED...]\n\n" + tail


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def extract_core_metadata(ocr_text: str, title: str) -> dict:
    ocr_text = select_text_window(ocr_text)

    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=2000,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert analyst of Environmental Impact Statements (EIS). "
                    "You will be given OCR text from a scanned EIS document.\n\n"
                    "Extract the following and respond ONLY with valid JSON "
                    "(no markdown, no backticks, no preamble):\n\n"
                    "{\n"
                    '  "summary": "<your summary here>",\n'
                    '  "location": "<primary location>",\n'
                    '  "key_people_and_groups": ["<name 1>", "<name 2>", "..."],\n'
                    '  "notable_quotes": [{"quote": "...", "attribution": "..."}, ...]\n'
                    "}\n\n"
                    "GUIDELINES FOR EACH FIELD:\n\n"
                    "summary (~100 words): Write in plain, everyday language that anyone "
                    "could understand — no jargon, no government-speak. "
                    "What was being proposed? Where? Why? What did it mean for the "
                    "community and environment?\n\n"
                    "location: The primary geographic area — be as specific as possible "
                    "(city/town, county, state). If a corridor, name the endpoints.\n\n"
                    "key_people_and_groups: 3-5 agencies, companies, community groups, "
                    "or named individuals prominently mentioned. Always include the lead "
                    "agency and any major opponents or supporters.\n\n"
                    "notable_quotes: A list of 0–3 objects, each with a \"quote\" and an "
                    "\"attribution\". Leave this list EMPTY unless you find something "
                    "genuinely worth preserving — a line that is emotionally resonant, "
                    "historically revealing, or captures a community's fear, hope, or "
                    "resistance in vivid human terms. The bar is high. Skip it if the "
                    "document only has bureaucratic language.\n\n"
                    "When you do include a quote:\n"
                    "- Copy it verbatim (silently fix obvious OCR scan errors only)\n"
                    "- It must be a complete sentence or passage, not a fragment\n"
                    "- It should feel like something a person could read aloud and be moved by\n"
                    "- Attribute it as specifically as possible: a named individual, an agency "
                    "statement, a community group's testimony, or at minimum the document "
                    "section it came from (e.g. 'Section 4.3 – Socioeconomic Impacts')\n\n"
                    "Format: [{\"quote\": \"...\", \"attribution\": \"...\"}, ...]"
                )
            },
            {
                "role": "user",
                "content": f"Document title: {title}\n\nOCR TEXT:\n{ocr_text}"
            }
        ]
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# STEP 4: Geocode location
# ---------------------------------------------------------------------------

def geocode_location(location_str: str) -> dict:
    if not location_str or location_str.lower() in ("unknown", "n/a", ""):
        return {}
    try:
        time.sleep(1.1)  # Nominatim requires >= 1s between requests
        result = geolocator.geocode(location_str, timeout=10)
        if result:
            return {
                "latitude":        round(result.latitude, 6),
                "longitude":       round(result.longitude, 6),
                "geocoded_address": result.address
            }
    except Exception as e:
        log.warning(f"  Geocoding failed for '{location_str}': {e}")
    return {}


# ---------------------------------------------------------------------------
# STEP 5: Theme classification
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def classify_theme(summary: str, title: str) -> dict:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=300,
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a classifier for Environmental Impact Statements. "
                    "Given a document title and summary, assign it to 1-2 themes "
                    "and 1-3 subthemes from the list below. Respond ONLY with valid JSON "
                    "(no markdown, no backticks):\n\n"
                    '{"theme": ["<theme name>"], "subthemes": ["<subtheme name>"]}\n\n'
                    f"AVAILABLE THEMES:\n{json.dumps(THEMES, indent=2)}"
                )
            },
            {
                "role": "user",
                "content": f"Title: {title}\nSummary: {summary}"
            }
        ]
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# STEP 6: External context + project status
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def get_external_context(summary: str, title: str, location: str) -> dict:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=800,
        temperature=0.3,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a knowledgeable historian of U.S. infrastructure and "
                    "environmental policy.\n\n"
                    "Given an EIS title, summary, and location, provide:\n\n"
                    "1. external_context (2-4 sentences): plain language backstory. "
                    "Why was this project proposed? Was there public pushback? "
                    "What ultimately happened? Do NOT make things up — if you "
                    "genuinely don't know, return an empty string.\n\n"
                    "2. project_status: one of:\n"
                    '   "Completed" | "Incomplete" | "Never started" | "unknown"\n\n'
                    "Respond ONLY with valid JSON (no markdown, no backticks):\n"
                    '{"external_context": "...", "project_status": "..."}'
                )
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\n"
                    f"Location: {location}\n"
                    f"Summary: {summary}"
                )
            }
        ]
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# MAIN PIPELINE
# ---------------------------------------------------------------------------

def load_existing_results() -> list[dict]:
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            return json.load(f)
    return []


def save_results(results: list[dict]):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(results)} results to {OUTPUT_FILE}")


def process_single_work(raw_work: dict) -> Optional[dict]:
    """Full pipeline for one NUL work. Returns result dict or None on failure."""
    work_id = raw_work.get("id", "")
    title   = raw_work.get("title", "Untitled")
    log.info(f"Processing: {title} ({work_id})")

    # --- Preserve NUL metadata ---
    nul_metadata = extract_nul_metadata(raw_work)

    # --- Find pre-existing OCR text ---
    match = find_ocr_text(raw_work)
    if match is None:
        log.warning(f"  No OCR text found in {TEXT_FILE} for {work_id} — skipping.")
        return None
    doc_id, ocr_text = match
    log.info(f"  Matched to doc_id: {doc_id} ({len(ocr_text):,} chars of OCR text)")

    if len(ocr_text.strip()) < 100:
        log.warning(f"  OCR text too short, skipping.")
        return None

    # --- Core metadata ---
    try:
        core            = extract_core_metadata(ocr_text, title)
        summary         = core.get("summary", "")
        location        = core.get("location", "")
        key_people      = core.get("key_people_and_groups", [])
        notable_quotes  = core.get("notable_quotes", [])
    except Exception as e:
        log.error(f"  Core metadata extraction failed: {e}")
        summary, location, key_people, notable_quotes = "", "", [], []

    # --- Geocoding ---
    coords = geocode_location(location)

    # --- Theme classification ---
    try:
        theme_data = classify_theme(summary, title)
    except Exception as e:
        log.error(f"  Theme classification failed: {e}")
        theme_data = {"theme": [], "subthemes": []}

    # --- External context ---
    try:
        context_data = get_external_context(summary, title, location)
    except Exception as e:
        log.error(f"  External context failed: {e}")
        context_data = {"external_context": "", "project_status": "unknown"}

    return {
        "nul_metadata": nul_metadata,
        "enrichments": {
            "doc_id":               doc_id,   # the key from docs_with_digits.json
            "summary":              summary,
            "location":             location,
            "coordinates":          coords,
            "key_people_and_groups": key_people,
            "notable_quotes":       notable_quotes,
            "theme":                theme_data.get("theme", []),
            "subthemes":            theme_data.get("subthemes", []),
            "external_context":     context_data.get("external_context", ""),
            "project_status":       context_data.get("project_status", "unknown"),
        },
        "processing": {
            "ocr_source":    TEXT_FILE,
            "ocr_chars":     len(ocr_text),
            "llm_model":     LLM_MODEL,
            "processed_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    }


def main():
    log.info("=" * 60)
    log.info("EIS Document Processing Pipeline")
    log.info("=" * 60)

    # Resume support
    results = load_existing_results()
    processed_ids = {r["nul_metadata"]["id"] for r in results if "nul_metadata" in r}
    log.info(f"Already processed: {len(processed_ids)} documents")

    # Fetch NUL works
    works = fetch_collection_works()

    remaining = [w for w in works if w.get("id") not in processed_ids]
    log.info(f"Remaining to process: {len(remaining)} documents")

    if not remaining:
        log.info("All documents already processed.")
        return

    # Report any docs in JSON that have no NUL match (useful for debugging)
    matched_doc_ids: set[str] = set()

    batch_count = 0
    for i, work in enumerate(remaining):
        log.info(f"\n--- Document {i+1}/{len(remaining)} ---")
        result = process_single_work(work)
        if result:
            results.append(result)
            matched_doc_ids.add(result["enrichments"]["doc_id"])
            batch_count += 1

        if batch_count >= BATCH_SIZE:
            save_results(results)
            batch_count = 0

    # Final save
    save_results(results)

    # Report unmatched JSON docs
    unmatched = set(DOCS.keys()) - matched_doc_ids
    if unmatched:
        log.warning(f"{len(unmatched)} docs in {TEXT_FILE} had no NUL match:")
        for uid in sorted(unmatched):
            log.warning(f"  {uid}")

    log.info(f"\nDone. {len(results)} documents written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
