# Tool contracts

Every tool is an MCP tool and `POST /api/tools/<name>`. Arguments are flat JSON.
Unknown fields are rejected. The response envelope is:

```json
{"success":true,"data":{},"metadata":{"duration_ms":125,"truncated":false},"error":null}
```

Failure returns `data: null` and an error with `code`, `message`, `retryable`,
and `next_operation`. REST failures use 400 (schema errors 422); MCP uses `isError`
plus the same structured envelope. Transport authentication uses 401. Approval
endpoint errors use 403. Authenticated artifact reads use 404 for missing files.

Aggregate tool data is capped at `MAX_TOOL_RESPONSE_CHARS` (24000 by default).
Text and lists may be shortened to meet that budget, with `truncated=true`.
IDs and citation URLs are never cut. Paginated file lists adjust `next_offset`
to the number of records actually returned. Search fails recoverably when all
usable results are absent and upstream engines report errors, while partial
results include compact `warnings`.

| Tool | Parameters | Result |
| --- | --- | --- |
| `web_search` | `query` (1–1000 chars), `limit=5` (1–20), `language="en"` | query and ordered, deduplicated titles, URLs, snippets ≤500 chars, engine and upstream warnings |
| `web_fetch` | `url`, `max_chars=12000` (100–100000, clamped globally) | title, requested/source/canonical URLs, text, ≤30 links, status, content type |
| `browser_open` | `url`, optional `session_id` | session ID, URL, title, main tab ID |
| `browser_snapshot` | `session_id`, `max_chars=8000` | accessibility text, ≤80 interactive element refs, snapshot ID |
| `browser_click` | `session_id`, `ref`, optional `approval_token` | navigate link without handlers; non-link click requires approval |
| `browser_type` | `session_id`, `ref`, `text` (≤4000 chars), `approval_token` | fill control with exact approved text; does not press Enter |
| `browser_scroll` | `session_id`, `pixels=700` (−5000–5000) | updated page metadata |
| `browser_screenshot` | `session_id` | saved viewport PNG metadata, artifact ID/URI |
| `browser_tabs` | `session_id` | one main tab; additional tabs/popups unsupported |
| `browser_close` | `session_id` | context closed |
| `file_download` | `url`, optional `filename` (≤180 chars) | persistent streamed artifact metadata |
| `browser_download` | `session_id`, `ref`, optional `filename` | captured link-download metadata; bounded bytes + Chromium Blob event |
| `file_inspect` | `file_id` | saved artifact metadata; requires its file still exist |
| `pdf_read` | `file_id`, `page_start=1`, optional `page_end`, `max_chars=12000` (100–100000, clamped to `MAX_FETCH_CHARS`), `text_offset=0` | total pages, page-numbered text, source URL and continuation cursors |
| `file_list` | `limit=20` (1–100), `offset=0` | newest files, optional `next_offset` |

URLs are ≤4096 characters, HTTP/HTTPS only, public addresses and allowed ports.
Session/file IDs are generated 32-character hexadecimal strings. References are
`<12-character snapshot ID>:<element index>`, session-scoped and ephemeral.
Every snapshot/interaction clears old refs, and DOM changes make refs stale.
Request another snapshot when receiving `stale_reference`.

Canonical URLs are webpage assertions, included for citation metadata; the service
does not fetch them automatically. Treat them and extracted text as untrusted.
Search results are upstream data; actual fetches/navigation still check policy.

File metadata includes `file_id`, `original_url`, `filename`, `content_type`, `size`,
`sha256`, `downloaded_at` (UTC), `storage_location` (managed relative name),
`resource_uri`, `status="complete"`, and `kind`. `artifact://<id>` is an application
identifier, not a registered MCP resource; fetch bytes through the authenticated
HTTP artifact route. Files are never executed or parsed as instructions.

## PDF reading

Download a public PDF using `file_download` or `browser_download`, then supply the
saved `file_id` to `pdf_read`. URLs and filesystem paths are not accepted by this
tool. A PDF header is required; a `.pdf` extension or MIME type alone is insufficient.
PDFs served as `application/octet-stream` can still be read.

`page_start` and `page_end` are inclusive, 1-based page numbers. Omitting `page_end`
selects up to 5 pages, subject to the configured per-call limit. Explicit ranges
must fit both the document and `PDF_MAX_PAGES_PER_CALL`. Only stored PDFs up to
`PDF_MAX_FILE_SIZE_MB` are read. There is no password argument.

Each result includes `file_id`, `filename`, `source_url`, `untrusted=true`,
`total_pages`, and `pages`. Each page contains `page_number`, `text`, `text_offset`,
`has_text`, and `truncated`. Character limits apply across all returned page text.
`has_text=false` means no text layer was extracted; it does not distinguish blank
pages from scanned/graphics-only pages. OCR and visual/layout inspection are not
implemented. Text order can differ from visual reading order in complex layouts.

Continue while `next_page` is non-null, using `page_start=next_page` and
`text_offset=next_text_offset`. The offset applies only to the first requested
page. This preserves text even when a single page exceeds the character or JSON
response budget. The cursor can point within the current page or to the next one.
The envelope's `metadata.truncated` marks output curtailed within the selected
range; a deliberate page-range selection can still have a next-page cursor.

PDF error codes include `invalid_pdf`, `encrypted_pdf`, `pdf_too_large`,
`pdf_resource_limit`, `pdf_page_limit`, `invalid_page_range`, `invalid_text_offset`,
`unsupported_content_type`, and `file_not_found`. These return the common envelope
and MCP `isError`, rather than parser diagnostics or document content in errors.

## Human approval

The agent has only `API_KEY`. A human reviewing the action uses the separate
credential to grant a specific action. No MCP approval-issuing tool exists.
The following is an operator request, using a fresh snapshot's session and ref:

```bash
curl -H 'Authorization: Bearer YOUR_API_KEY' \
  -H 'X-Human-Approval-Key: YOUR_HUMAN_APPROVAL_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"action":"browser_type","session_id":"SESSION_ID","ref":"SNAPSHOT_REF","text":"documentation"}' \
  http://127.0.0.1:8000/api/approvals
```

The result contains `approval_token`, valid for 60 seconds and one use. Give only
that token to the agent with the exact action. A mismatch consumes/rejects it.
For `browser_click`, omit `text`. Even approved browser traffic remains GET-only;
POST form submissions, purchases and destructive/account operations are blocked.

## Workflow

Search → select result URL → fetch → browser_open if needed → browser_snapshot →
follow a link with browser_click → snapshot again → browser_download on a link →
file_inspect → browser_close. Unit/integration tests exercise this workflow using
local deterministic fixtures, including human-granted typing and a button click.

Common recoverable codes: `timeout`, `upstream_unavailable`, `search_unavailable`,
`stale_reference`, `session_not_found`, `session_limit`, `approval_required`.
Policy codes: `blocked_url`, `blocked_address`, `invalid_filename`,
`download_too_large`, `storage_quota_exceeded`, `unsafe_download_action`.
Binary fetches return `unsupported_content_type` and recommend `file_download`.
