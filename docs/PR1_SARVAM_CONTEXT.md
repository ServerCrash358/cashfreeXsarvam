# PR1_SARVAM_CONTEXT.md: Sarvam Document AI facts for PR 1

Source of truth for endpoint names, parameters and limits in PR 1. Everything marked **SDK** was read from the installed `sarvamai==0.1.48` source on 21 Nov 2026. Everything marked **UNVERIFIED** must be confirmed by `scripts/probe_vision.py` and then updated here.

This replaces section 3 of the PR 1 brief, which had three errors: Extract has no `language` argument, `client.document_intelligence` does exist, and Parse's output format is chosen at fetch time.

## Auth and base (SDK)
- Header `api-subscription-key: <key>`. Base URL `https://api.sarvam.ai`.
- `SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])`.
- Use `client.doc_ai`. `client.document_intelligence` also exists in 0.1.48 (older job API: `create_job` / `upload_file` / `start` / `wait_until_complete` / `download_output`). Do not mix them.

## Lifecycle (SDK)
create → poll → fetch. Terminal statuses: `completed`, `partially_completed`, `failed`, `rejected`. Results before a terminal status return 409.

```python
job = client.doc_ai.extract(
    file=[("inv.png", fh, "image/png")],   # a list, even for one file
    schema=schema_json(),                  # exactly one of schema / config_id
    output_format="json",                  # json | csv | xlsx
    mode="basic",                          # ALWAYS basic, see below
)
st  = client.doc_ai.get_status(job.job_id)   # st.status, st.usage.pages_total / pages_failed
res = client.doc_ai.get_results(job.job_id)  # extract: result, annotations, usage, version
```

## Extract (SDK)
- Endpoint `POST /doc-ai/v1/job/extract`, multipart. Arguments: `file` or `upload_ids`, `schema` or `config_id`, `output_format`, `classification`, `model`, `mode`.
- **No `language` argument.** It can be forced with `request_options={"additional_body_parameters": {"language": "ta-IN"}}`, but whether the server reads it is UNVERIFIED. Off by default (`extract_send_language` in `config/reading.json`).
- **`mode`**: `basic` reads each field where it is printed. `advanced` adds a whole-document pass that "checks that line items add up to the total". That pass could repair exactly the arithmetic traps we must catch, so PR 1 refuses to run with `advanced` (`ReadingConfig.load` raises).
- **Results** carry `result` (values shaped by the schema) and `annotations`, which mirror `result` with every leaf replaced by `confidence` and `sources`. The SDK evidence type has `input_page`, `source_page`, `block_ids`, `source` and `region` (`{x, y, width, height, coordinate_space}`, normalised). So per-field confidence and page numbers come from Extract, and possibly the crop box. UNVERIFIED: the exact leaf shape on our invoices.
- Schema rules: root `{"type": "object", "properties": {...}}`, non-empty; every field needs a `type` and a non-empty `description`; types string, number, integer, boolean, object, array; optional `enum`; max nesting depth 4.
- **Every field in our schema is `string`.** A `number` field makes the model convert the digits itself and return a JSON float, and we lose the native string.
- Accepted file types for Extract: UNVERIFIED. Classify and Split accept PDF, PNG, JPEG and TIFF, and the older job API accepts PDF, PNG, JPG and ZIP.

## Parse (SDK)
- `client.doc_ai.parse(file=[...], language="ta-IN", content_type="printed"|"handwritten"|"mixed", model=...)`.
- `language` is BCP-47 and **defaults to Indic**: an English document needs `en-IN`. `auto` is not a value.
- No `output_format` at creation. Pick it when fetching: `get_results(job_id, format="json"|"md"|"html")`.
- The docstring says Parse JSON results include blocks with text, tag and bounding box. Parse is off by default (`parse_for_crops`) because Extract annotations may already carry regions.

## Limits (reported, UNVERIFIED)
- Extract 20 pages / 200 MB per PDF; Parse 30 pages; some pages mention 10 pages per job. Irrelevant for single-page invoices.
- Latency 20-90 s per job. Multi-read on 8 demo invoices is 24 Extract jobs: pre-run with `scripts/read_batch.py`, demo with `PANCH_VISION_OFFLINE=1`.
- `client.doc_ai.get_capabilities()` returns limits for Classify and Split only.

## Transliteration (SDK, vendor names only, behind a flag)
- `client.text.transliterate(input=..., source_language_code="auto"|"ta-IN"|..., target_language_code="en-IN")`. Not `/translate`: that endpoint can translate a name instead of transliterating it.
- `vendor_key()` must stay pure, so PR 1 uses a local Tamil/Devanagari table (`panch/normalise/translit.py`). Sarvam transliteration is not wired in.

## Never
- `output_format="markdown"` (the value is `md`, and only for Parse results).
- `language_code=` on Document AI.
- `mode="advanced"` on Extract.
- A Sarvam chat model to fill fields (team rule). The in-rule fallback for bad handwriting is Parse markdown plus deterministic regex.
