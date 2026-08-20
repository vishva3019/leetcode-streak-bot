#!/usr/bin/env python3

import json
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = Path("/tmp/neetcode-leetcode")
PYTHON_DIR = SOURCE_DIR / "python"
METADATA_FILE = SOURCE_DIR / ".problemSiteData.json"
SOLUTIONS_FILE = BOT_DIR / "solutions.json"

print("Loading NeetCode repository...")

if not SOURCE_DIR.exists():
    raise SystemExit("ERROR: NeetCode repository not found.")

if not METADATA_FILE.exists():
    raise SystemExit("ERROR: .problemSiteData.json not found.")

if not PYTHON_DIR.exists():
    raise SystemExit("ERROR: python directory not found.")

with open(METADATA_FILE, "r", encoding="utf-8") as f:
    metadata = json.load(f)

with open(SOLUTIONS_FILE, "r", encoding="utf-8") as f:
    existing = json.load(f)

existing_ids = {str(x["question_id"]) for x in existing}

print(f"Existing solutions: {len(existing)}")

added = []
skipped_existing = 0
skipped_not_easy = 0
skipped_no_python = 0
skipped_premium = 0
skipped_missing_file = 0

for item in metadata:
    question_code = item.get("code")
    title = item.get("problem")
    difficulty = item.get("difficulty")
    slug = str(item.get("link", "")).strip("/")

    if not question_code or not title or not slug:
        continue

    # Only standard LeetCode Easy problems.
    if difficulty != "Easy":
        skipped_not_easy += 1
        continue

    if not item.get("python"):
        skipped_no_python += 1
        continue

    # Skip premium/non-LeetCode problems.
    if item.get("premium"):
        skipped_premium += 1
        continue

    # Example: 0217-contains-duplicate
    parts = question_code.split("-", 1)

    if len(parts) != 2:
        continue

    question_id = str(int(parts[0]))
    filename = f"{question_code}.py"
    solution_path = PYTHON_DIR / filename

    if question_id in existing_ids:
        skipped_existing += 1
        continue

    if not solution_path.exists():
        skipped_missing_file += 1
        continue

    code = solution_path.read_text(encoding="utf-8").strip()

    if not code:
        continue

    added.append({
        "question_id": question_id,
        "title": title,
        "title_slug": slug,
        "difficulty": "Easy",
        "lang": "python3",
        "typed_code": code
    })

    existing_ids.add(question_id)

print()
print("Import summary")
print("=" * 50)
print(f"Existing solutions:       {len(existing)}")
print(f"New Easy Python solutions: {len(added)}")
print(f"Already in bank:           {skipped_existing}")
print(f"Non-Easy skipped:          {skipped_not_easy}")
print(f"No Python solution:        {skipped_no_python}")
print(f"Premium skipped:           {skipped_premium}")
print(f"Missing source file:       {skipped_missing_file}")

# Keep your existing solutions first, then add imported solutions.
merged = existing + added

# Safety check for duplicate IDs.
seen = set()
deduplicated = []

for solution in merged:
    qid = str(solution["question_id"])

    if qid in seen:
        continue

    seen.add(qid)
    solution["question_id"] = qid
    deduplicated.append(solution)

with open(SOLUTIONS_FILE, "w", encoding="utf-8") as f:
    json.dump(deduplicated, f, indent=2, ensure_ascii=False)

print()
print(f"Final solution bank: {len(deduplicated)}")
print(f"Updated: {SOLUTIONS_FILE}")
