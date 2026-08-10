# QR Item Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 발표일 기준 물품 11종의 CSV/JSON 데이터셋, 실제 선반 위치 SQL, 재고 적재 SQL 템플릿과 검증 가능한 개별 QR PNG 생성 도구를 제공한다.

**Architecture:** CSV를 사람이 수량을 입력하는 단일 원본으로 사용하고, Python 도구가 행을 검증한 뒤 QR에 넣을 compact JSON과 PNG를 생성한다. JSON 템플릿과 SQL은 같은 식별자·날짜·위치 코드를 사용하며, 위치는 QR payload가 아니라 DB 관계로 관리한다.

**Tech Stack:** Python 3.10+, standard library (`csv`, `json`, `datetime`, `pathlib`, `argparse`), `qrcode[pil]`, pytest, MySQL 8.0 SQL

## Global Constraints

- 발표 기준일은 `2026-08-25`이다.
- 상온 유통기한은 `D+3일`~`D+5일`, 냉장은 `D+5일`~`D+7일`, 냉동은 `D+365일`~`D+368일`이다.
- `storage_code`는 `ambient`, `chilled`, `frozen`만 허용한다.
- CSV의 `quantity`는 사용자가 입력하도록 비워 두고 JSON 템플릿에서는 `null`로 둔다.
- 실제 QR PNG 생성 시 `quantity`는 양의 정수여야 한다.
- 정확한 `location_code`는 QR payload에 넣지 않는다.
- 물품 QR payload schema는 `trihouse.item.v1`이다.
- 기존 MySQL v4 스키마는 변경하지 않는다.

---

### Task 1: Dataset Contract and Validation Tests

**Files:**
- Create: `db/datasets/item_qr_dataset.csv`
- Create: `db/datasets/item_qr_payloads.json`
- Create: `db/tests/test_item_qr_dataset.py`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-10-qr-marker-item-dataset-design.md`
- Produces: CSV columns `schema,item_id,product_code,item_name,expiry_date,storage_code,quantity,location_code`; JSON array of the seven QR payload fields

- [ ] **Step 1: Write dataset tests**

Test that the CSV contains exactly 11 rows, all required columns, unique IDs/codes, the specified shelf assignment, blank quantities, valid temperature codes, and exact presentation-relative expiry dates. Test that JSON contains the same QR fields with `quantity` set to `null` and excludes `location_code`.

```python
def test_dataset_has_expected_inventory(item_rows):
    assert len(item_rows) == 11
    assert {row["item_name"] for row in item_rows} == {
        "오렌지", "딸기", "귤", "커피", "샌드위치", "요구르트", "우유",
        "냉동 삼겹살", "냉동 만두", "아이스크림바", "아이스크림콘",
    }
    assert all(row["quantity"] == "" for row in item_rows)
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `pytest -q db/tests/test_item_qr_dataset.py`
Expected: FAIL because the CSV and JSON files do not exist.

- [ ] **Step 3: Create the CSV and JSON datasets**

Create all 11 rows using the approved IDs, location codes, and dates. Keep `quantity` empty in CSV and use JSON `null`; do not include `location_code` in a QR payload object.

- [ ] **Step 4: Run dataset tests**

Run: `pytest -q db/tests/test_item_qr_dataset.py`
Expected: PASS.

- [ ] **Step 5: Commit the dataset contract**

```bash
git add db/datasets/item_qr_dataset.csv db/datasets/item_qr_payloads.json db/tests/test_item_qr_dataset.py
git commit -m "feat: add item QR dataset"
```

### Task 2: QR Payload and PNG Generator

**Files:**
- Create: `db/tools/generate_item_qr.py`
- Create: `db/tools/requirements-qr.txt`
- Create: `db/tests/test_generate_item_qr.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: CSV columns from Task 1
- Produces: `load_rows(path: Path) -> list[dict[str, object]]`, `compact_payload(row: dict[str, object]) -> str`, `generate_qr_files(csv_path: Path, output_dir: Path) -> list[Path]`
- CLI: `python3 db/tools/generate_item_qr.py --input <csv> --output <directory>`

- [ ] **Step 1: Write failing unit tests**

Cover compact UTF-8 JSON, allowed storage codes, ISO expiry dates after `2026-08-25`, duplicate IDs/product codes, positive integer quantity, safe item IDs, and one PNG per valid CSV row.

```python
def test_compact_payload_preserves_korean(valid_row):
    text = compact_payload(valid_row)
    assert "오렌지" in text
    assert " " not in text
    assert json.loads(text)["quantity"] == 3

def test_blank_quantity_is_rejected(valid_row):
    valid_row["quantity"] = ""
    with pytest.raises(ValueError, match="quantity"):
        compact_payload(valid_row)
```

- [ ] **Step 2: Run generator tests and confirm failure**

Run: `pytest -q db/tests/test_generate_item_qr.py`
Expected: FAIL because `db.tools.generate_item_qr` does not exist.

- [ ] **Step 3: Implement validation and generation**

Use `csv.DictReader`, `datetime.date.fromisoformat`, and `json.dumps(payload, ensure_ascii=False, separators=(",", ":"))`. Import `qrcode` only inside PNG generation and raise a message directing the user to install `db/tools/requirements-qr.txt` if unavailable. Generate QR error correction Q, `box_size=10`, `border=4`, and save `<item_id>.png`.

- [ ] **Step 4: Add dependency and generated-output ignore rule**

Set `db/tools/requirements-qr.txt` to:

```text
qrcode[pil]>=8.0,<9.0
```

Add `/db/datasets/generated_qr/` to `.gitignore`.

- [ ] **Step 5: Run generator tests**

Run: `pytest -q db/tests/test_generate_item_qr.py`
Expected: PASS, including PNG signature and file count assertions.

- [ ] **Step 6: Commit the QR generator**

```bash
git add .gitignore db/tools/generate_item_qr.py db/tools/requirements-qr.txt db/tests/test_generate_item_qr.py
git commit -m "feat: generate item QR images from CSV"
```

### Task 3: Location Seed and Inventory SQL Template

**Files:**
- Create: `db/datasets/seed_qr_demo_locations.sql`
- Create: `db/datasets/seed_item_qr_inventory.sql`
- Modify: `db/tests/test_item_qr_dataset.py`

**Interfaces:**
- Consumes: the 12 approved `location_code` values and the 11 dataset rows
- Produces: idempotent location inserts and guarded inventory-lot insert templates compatible with `db/schema_mysql.sql`

- [ ] **Step 1: Extend tests for SQL coverage**

Assert that every dataset `location_code` appears in the location SQL, all three rack parents and 12 slots exist, each temperature zone has four slots, and every `lot_code`/`product_code` appears in the inventory SQL. Assert the inventory template does not insert a positive stock quantity until the user supplies it.

- [ ] **Step 2: Run SQL coverage tests and confirm failure**

Run: `pytest -q db/tests/test_item_qr_dataset.py`
Expected: FAIL because SQL files do not exist.

- [ ] **Step 3: Create idempotent location SQL**

Insert/upsert three `rack` locations and twelve `slot` locations. Resolve `parent_location_id` with a subquery on the rack code, set `temperature_zone`, and put `level` and `side` (`left`/`right`) in JSON `metadata`.

- [ ] **Step 4: Create guarded inventory SQL template**

Document one user-editable quantity variable per product and use a preflight query that lists NULL/non-positive quantities before the transaction. Insert `inventory_lots` by resolving each `location_id` from `location_code`; initialize `reserved_qty=0` and `state='stored'`. Include corresponding `inventory_moves` rows in the same transaction, using inserted lot IDs resolved by unique `lot_code`.

- [ ] **Step 5: Run SQL coverage tests**

Run: `pytest -q db/tests/test_item_qr_dataset.py`
Expected: PASS.

- [ ] **Step 6: Commit SQL assets**

```bash
git add db/datasets/seed_qr_demo_locations.sql db/datasets/seed_item_qr_inventory.sql db/tests/test_item_qr_dataset.py
git commit -m "feat: add QR demo location and inventory seeds"
```

### Task 4: Usage Documentation and End-to-End Verification

**Files:**
- Create: `docs/database/qr_item_dataset_guide.md`
- Modify: `db/tests/test_generate_item_qr.py`

**Interfaces:**
- Consumes: all artifacts from Tasks 1–3
- Produces: copy-paste commands for entering quantities, installing the QR dependency, generating PNGs, decoding with OpenCV, and loading SQL

- [ ] **Step 1: Add an end-to-end CLI test**

Copy the CSV to a temporary path, fill every quantity with `1`, run the CLI via `subprocess`, and assert 11 named PNG files are produced. Decode at least one generated QR when OpenCV with `QRCodeDetector` is installed; otherwise keep decoding as a documented manual verification rather than making OpenCV a project dependency.

- [ ] **Step 2: Run the CLI test and confirm its initial failure**

Run: `pytest -q db/tests/test_generate_item_qr.py`
Expected: FAIL until CLI exit behavior and output summary match the test.

- [ ] **Step 3: Complete CLI output and write the guide**

The guide must include:

```bash
python3 -m pip install -r db/tools/requirements-qr.txt
python3 db/tools/generate_item_qr.py \
  --input db/datasets/item_qr_dataset.csv \
  --output db/datasets/generated_qr
```

Explain that users must fill `quantity` first, Google text QR generation accepts the same compact JSON, `location_code` stays out of the QR, and OpenCV returns text that is parsed with `json.loads`.

- [ ] **Step 4: Run focused verification**

Run: `pytest -q db/tests/test_item_qr_dataset.py db/tests/test_generate_item_qr.py`
Expected: PASS.

- [ ] **Step 5: Run repository DB tests**

Run: `pytest -q db/tests`
Expected: PASS.

- [ ] **Step 6: Run a manual generation smoke test**

Use a temporary CSV with quantity `1` and a temporary output directory, then verify that exactly 11 PNG files are produced and the decoded JSON for orange has `expiry_date="2026-08-28"`, `storage_code="ambient"`, and `quantity=1`.

- [ ] **Step 7: Commit documentation and final test**

```bash
git add docs/database/qr_item_dataset_guide.md db/tests/test_generate_item_qr.py
git commit -m "docs: explain QR item dataset workflow"
```
