# repair/04_import_contact_repair.md — Import / Contact Creation Repair

---

## Current Import Architecture

### Files
- `backend/app/imports/router.py` — endpoints `/preview`, `/commit`
- `backend/app/imports/service.py` — `preview_import()`, `commit_import()`
- `frontend/src/App.tsx` ImportPanel — CSV parsing, form, preview display, commit

### In-Memory Preview State (CONFIRMED risk)

```python
# imports/service.py (inferred from architecture_test.md)
PREVIEWS: dict[str, PreviewResult] = {}  # process-local dict

async def preview_import(rows, db) -> PreviewResult:
    result = _validate_rows(rows, db)
    batch_id_temp = str(uuid4())
    PREVIEWS[batch_id_temp] = result  # stored in memory only
    return result

async def commit_import(batch_id_temp, db) -> CommitResult:
    preview = PREVIEWS.get(batch_id_temp)
    if preview is None:
        raise ValueError("Preview not found or expired")
    # ... write to DB
    del PREVIEWS[batch_id_temp]
```

**Problem:** If `uvicorn` restarts between preview and commit (hot-reload during dev,
crash, or deploy), `PREVIEWS` is empty. Commit returns "not found" or 0 rows written.
The frontend may show a misleading success toast if it doesn't distinguish this error.

---

## Multi-Column CSV Mapping

### Expected CSV headers (based on contact model columns)
```
email, creator_name, business_name, website_url, notes, personalization, lead_category, tags
```

### Real-world CSV headers (what users actually have)
```
Email Address, Name, Website, Notes, Tags, Context
Email, Full Name, Site, Info, Category
```

### Current behavior
If headers don't match expected names, the service either:
- Uses first column as email regardless of header name
- Skips unrecognized columns silently

### Evidence of the problem
Image 03 shows source = "manualmanual" for crce.9955.ce@gmail.com — this double-value
suggests a field mapping bug where the source field was written twice or the wrong column
was mapped to `source`.

---

## Duplicate / Suppression / Invalid Handling at Commit

### Current flow
```
preview_import():
  Per row:
    1. Validate email regex → invalid_email
    2. Check contacts table (email UNIQUE) → duplicate
    3. Check suppressions table → suppressed
    4. Check blocked_domains setting → domain_blocked
    5. Check required fields → missing_field
  Store in PREVIEWS.

commit_import():
  Re-run steps 2-4 only (replay-safe re-validation)
  Insert accepted rows only.
```

### Known gaps
1. **Previously deleted contacts**: A soft-deleted contact (deleted_at IS NOT NULL) still has
   their email in the contacts table. Duplicate check on email will hit the deleted row and mark
   the new import as `duplicate`, preventing re-import after deletion.
   **Fix**: Change duplicate check to `WHERE email=? AND deleted_at IS NULL`. If a deleted contact
   is re-imported, restore them with `deleted_at=NULL, status='imported'`.

2. **Silent row rejection**: The commit API returns a summary (accepted: N, rejected: M) but
   the frontend only shows a success toast with the total number. The operator cannot see WHY
   rows were rejected.
   **Fix**: Return and display per-row outcome in commit response.

3. **"Submit" button vs. Commit** (Image 02): The Import surface shows THREE buttons: Preview,
   Commit, and Submit. The Submit button appears to be a single-row manual entry path
   (bypasses CSV preview flow). This is acceptable but should be clearly labeled
   "Add Single Contact" to avoid confusion with CSV commit.

---

## Proposed Fix: DB-Backed Preview

### New column: `import_batches.status`
```sql
ALTER TABLE import_batches ADD COLUMN status TEXT NOT NULL DEFAULT 'committed';
-- Values: 'preview' | 'committed'
```

### Updated flow
```python
async def preview_import(rows, db) -> PreviewResult:
    # Write preview state to DB instead of in-memory dict
    batch = ImportBatch(
        id=str(uuid4()),
        status='preview',
        format=...,
        ...
    )
    db.add(batch)
    for i, row in enumerate(validated_rows):
        db.add(ImportRow(batch_id=batch.id, row_num=i, ...))
    await db.commit()
    return PreviewResult(batch_id=batch.id, rows=validated_rows)

async def commit_import(batch_id, db) -> CommitResult:
    batch = await db.get(ImportBatch, batch_id)
    if not batch or batch.status != 'preview':
        raise HTTPException(400, "Preview not found or already committed")
    # Re-validate
    rows = await db.execute(select(ImportRow).where(ImportRow.batch_id == batch_id))
    accepted_rows = [r for r in rows if _revalidate(r)]
    # Create contacts
    for row in accepted_rows:
        contact = Contact(...)
        db.add(contact)
    batch.status = 'committed'
    await db.commit()
    return CommitResult(...)
```

---

## Frontend Commit Response Display

### Current (insufficient)
```
Toast: "Imported 5 contacts"
```

### Proposed (per-row outcome table)
```
Import Results:
  ✅ Accepted: 3
  ⚠️  Duplicates (skipped): 1
  ❌ Invalid email: 1

Details:
  john@example.com — ✅ Accepted
  jane@existing.com — ⚠️ Already exists
  notanemail — ❌ Invalid email format
```

---

## Contact Query Invalidation After Commit

### Current issue
TanStack Query invalidation uses `queryClient.invalidateQueries({ queryKey: ['contacts'] })`.
If the contacts panel uses a different key (e.g., `['contacts', filterTag]`), it may not
re-fetch after commit.

### Fix
```typescript
// After successful commit:
queryClient.invalidateQueries({ queryKey: ['contacts'] }); // invalidate ALL contacts queries
```

Use `{ queryKey: ['contacts'] }` with no additional key suffix to invalidate all variants.

---

## Source = "manualmanual" Bug Fix

In `contacts/router.py` or `imports/service.py`, the source field is being set as:
```python
source = source_param + source_param  # bug: concatenated twice
```
Or more likely, the source field is receiving the value from two different places in one request.

**Fix**: Audit `backend/app/contacts/router.py` create contact handler and
`backend/app/imports/service.py` row-to-contact mapper for any place where source is
appended/concatenated rather than assigned.
