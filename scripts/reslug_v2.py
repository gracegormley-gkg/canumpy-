"""
Re-slug existing manifests to 50-char limit (matching Canopy's MAX_ENTRY_SLUG_LENGTH).
Reads manifests from manifests/, writes to manifests/ with new names,
and outputs collection-eis-v2.json.

Does NOT re-fetch any canvas data — works entirely from local files.
"""

import json
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS_DIR = REPO_ROOT / "manifests"
COLLECTION_IN = REPO_ROOT / "collection-eis.json"
COLLECTION_OUT = REPO_ROOT / "collection-eis-v2.json"
BASE_URL = "https://raw.githubusercontent.com/gracegormley-gkg/canumpy-/main"

MAX_SLUG_LEN = 50  # Must match Canopy's MAX_ENTRY_SLUG_LENGTH


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:MAX_SLUG_LEN].rstrip("-")


def build_slug_with_suffix(base: str, counter: int) -> str:
    """Mirrors Canopy's buildSlugWithSuffix."""
    suffix = f"-{counter}"
    base_limit = MAX_SLUG_LEN - len(suffix)
    trimmed_base = base[:base_limit].rstrip("-")
    return f"{trimmed_base}{suffix}"


# Load collection
print("Loading collection-eis.json...")
with open(COLLECTION_IN) as f:
    collection = json.load(f)

items = collection.get("items", [])
print(f"  {len(items)} items")

# Build old-filename → new-slug mapping
slug_seen: dict[str, int] = {}
renames: list[tuple[str, str, str]] = []  # (old_filename, new_slug, label)

for item in items:
    old_url = item["id"]
    old_filename = old_url.split("/")[-1].replace(".json", "")

    # Get label from the existing manifest file
    old_path = MANIFESTS_DIR / f"{old_filename}.json"
    if not old_path.exists():
        print(f"  MISSING: {old_filename}.json — skipping")
        continue

    with open(old_path) as f:
        manifest = json.load(f)

    label = manifest.get("label", {})
    if isinstance(label, dict):
        label_text = ""
        for lang, vals in label.items():
            if vals:
                label_text = vals[0]
                break
    else:
        label_text = str(label)

    slug_base = slugify(label_text)

    if slug_base in slug_seen:
        slug_seen[slug_base] += 1
        new_slug = build_slug_with_suffix(slug_base, slug_seen[slug_base])
    else:
        slug_seen[slug_base] = 0
        new_slug = slug_base

    renames.append((old_filename, new_slug, label_text[:60]))

# Report changes
changed = [(old, new, lbl) for old, new, lbl in renames if old != new]
unchanged = [old for old, new, _ in renames if old == new]
print(f"\n{len(changed)} manifests will be renamed, {len(unchanged)} unchanged")

# Apply: copy manifest files with new names, update their internal id field
new_collection_items = []
for old_filename, new_slug, label_text in renames:
    old_path = MANIFESTS_DIR / f"{old_filename}.json"
    new_path = MANIFESTS_DIR / f"{new_slug}.json"
    new_url = f"{BASE_URL}/manifests/{new_slug}.json"

    with open(old_path) as f:
        manifest = json.load(f)

    # Update the manifest's own id to the new URL
    manifest["id"] = new_url

    with open(new_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Build collection item with updated id
    new_item = dict(item for item in [
        (k, v) for item_obj in [
            next(i for i in items if i["id"].endswith(f"/{old_filename}.json"))
        ] for k, v in item_obj.items()
    ])
    new_item["id"] = new_url
    new_collection_items.append(new_item)

    if old_filename != new_slug:
        print(f"  {old_filename[:50]}")
        print(f"    → {new_slug}")

# Write new collection
new_collection = dict(collection)
new_collection["id"] = f"{BASE_URL}/collection-eis-v2.json"
new_collection["items"] = new_collection_items

with open(COLLECTION_OUT, "w") as f:
    json.dump(new_collection, f, indent=2, ensure_ascii=False)

print(f"\nWrote {COLLECTION_OUT.name} with {len(new_collection_items)} items")
print("\nNext steps:")
print("  1. Delete old long-named manifest files (optional, won't break anything)")
print("  2. git add manifests/ collection-eis-v2.json && git commit && git push")
print("  3. Update canopy.yml to point to collection-eis-v2.json")
