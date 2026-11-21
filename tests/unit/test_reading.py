"""Module A with a fake SDK: no network. Brief section 7 cases."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from panch.reading.config import ReadingConfig
from panch.reading.reader import VisionCacheMiss, get_read_artifacts, read_invoice
from panch.reading.schema import EXTRACT_SCHEMA
from panch.reading.vision import VisionClient

from .fakes import CLEAN_RESULT, ExplodingClient, FakeDocAi, FakeSdk, result_with


@pytest.fixture
def cfg(tmp_path):
    return ReadingConfig(cache_dir=tmp_path / "cache", poll_interval_s=0, job_timeout_s=30)


def _client(cfg, by_variant, **kw):
    doc = FakeDocAi(by_variant, **kw)
    return VisionClient(FakeSdk(doc), config=cfg, sleep=lambda s: None), doc


def _pdf(tmp_path, name="inv_B.pdf", body=b"%PDF-1.4 fake invoice"):
    p = tmp_path / name
    p.write_bytes(body)
    return p


def _png(tmp_path, name="inv_B.png"):
    PIL = pytest.importorskip("PIL.Image")
    p = tmp_path / name
    PIL.new("RGB", (60, 40), "white").save(p)
    return p


def test_clean_read_maps_every_field(tmp_path, cfg):
    client, doc = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)

    assert inv.total == Decimal("12390.00") and isinstance(inv.total, Decimal)
    assert inv.subtotal == Decimal("10500.00") and inv.tax == Decimal("1890.00")
    assert inv.cgst == inv.sgst == Decimal("945.00") and inv.igst is None
    assert inv.words_amount == Decimal("12390")
    assert inv.date == date(2026, 11, 3) and inv.date_ambiguous is False
    assert inv.number_raw == "INV-0042" and inv.number_norm == "42"
    assert inv.gstin == "33AAICP2912R1ZR" and inv.ifsc == "YESB0000262"
    assert inv.payee_name == "JOHN DOE"
    assert inv.account_number == "026291800001191"
    assert [(l.qty, l.rate, l.amount) for l in inv.lines] == [
        (Decimal("10"), Decimal("450.00"), Decimal("4500.00")),
        (Decimal("5"), Decimal("1200.00"), Decimal("6000.00")),
    ]
    assert inv.raw_native["total"] == "₹ 12,390.00"          # evidence of record, untouched
    assert inv.raw_native["lines[0].qty"] == "10 Nos"
    assert all(inv.stable.values()), {k: v for k, v in inv.stable.items() if not v}
    assert inv.pages["total"] == 1 and inv.confidence["total"] == pytest.approx(0.97)
    assert inv.id == "inv_" + inv.source_hash[:16]
    assert inv.vendor_key == "hrtvr mrkn"


def test_extract_call_is_basic_mode_string_schema_no_language_kwarg(tmp_path, cfg):
    client, doc = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    read_invoice(_pdf(tmp_path), client=client, config=cfg)
    call = doc.calls[0]
    assert call["mode"] == "basic" and call["output_format"] == "json"
    assert "language" not in call and "request_options" not in call
    schema = json.loads(call["schema"])

    def leaves(node):
        if node.get("type") == "object":
            for v in node["properties"].values():
                yield from leaves(v)
        elif node.get("type") == "array":
            yield from leaves(node["items"])
        else:
            yield node
    assert all(l["type"] == "string" and l["description"] for l in leaves(schema))
    assert schema == EXTRACT_SCHEMA


def test_variants_disagree_on_total_marks_unstable(tmp_path, cfg):
    client, _ = _client(cfg, {
        "orig": ("completed", CLEAN_RESULT),
        "binar": ("completed", result_with(total="₹ 12,890.00")),
        "up2x": ("completed", CLEAN_RESULT),
    })
    inv = read_invoice(_png(tmp_path), client=client, config=cfg)
    assert inv.stable["total"] is False
    assert inv.total == Decimal("12390.00")                 # orig kept, visibly unstable
    assert inv.stable["subtotal"] is True
    art = get_read_artifacts(inv, config=cfg)
    assert art["fields"]["total"]["unstable_reasons"] == ["variants_disagree"]
    assert art["fields"]["total"]["per_variant"] == {"orig": "12390.00", "binar": "12890.00", "up2x": "12390.00"}
    assert set(art["variants_read"]) == {"orig", "binar", "up2x"}


def test_variant_missing_a_value_counts_as_disagreement(tmp_path, cfg):
    client, _ = _client(cfg, {
        "orig": ("completed", CLEAN_RESULT),
        "binar": ("completed", result_with(ifsc="")),
        "up2x": ("completed", CLEAN_RESULT),
    })
    inv = read_invoice(_png(tmp_path), client=client, config=cfg)
    assert inv.stable["ifsc"] is False and inv.ifsc == "YESB0000262"


def test_partially_completed_keeps_good_data_flags_missing(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("partially_completed", result_with(total="", amount_in_words=""))})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    assert inv.total is None and inv.stable["total"] is False
    assert inv.subtotal == Decimal("10500.00") and inv.stable["subtotal"] is True
    art = get_read_artifacts(inv, config=cfg)
    assert "partial_job" in art["fields"]["total"]["unstable_reasons"]


def test_failed_job_gives_empty_unstable_invoice_not_exception(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("failed", {})})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    assert inv.total is None and inv.lines == []
    assert inv.stable and not any(inv.stable.values())


def test_unparseable_and_traditional_numerals_are_none_and_unstable(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("completed", result_with(total="௲௰", subtotal="ten thousand-ish"))})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    assert inv.total is None and inv.stable["total"] is False
    assert inv.raw_native["total"] == "௲௰"
    assert inv.subtotal is None and inv.stable["subtotal"] is False
    art = get_read_artifacts(inv, config=cfg)
    assert art["fields"]["total"]["unstable_reasons"] == ["traditional_tamil_numerals"]


def test_number_returned_by_vision_is_flagged(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("completed", result_with(total=12390.0))})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    assert inv.stable["total"] is False
    assert isinstance(inv.total, Decimal)


def test_incomplete_line_is_dropped_and_lines_unstable(tmp_path, cfg):
    rows = [dict(CLEAN_RESULT["line_items"][0]), dict(CLEAN_RESULT["line_items"][1], rate="")]
    client, _ = _client(cfg, {"orig": ("completed", result_with(line_items=rows))})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    assert len(inv.lines) == 1 and inv.stable["lines"] is False


def test_offline_reads_cache_and_never_calls_vision(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    f = _pdf(tmp_path)
    first = read_invoice(f, client=client, config=cfg)
    cfg.offline = True
    second = read_invoice(f, client=ExplodingClient(), config=cfg)
    assert second.total == first.total and second.raw_native == first.raw_native


def test_offline_cache_miss_is_loud(tmp_path, cfg):
    cfg.offline = True
    with pytest.raises(VisionCacheMiss):
        read_invoice(_pdf(tmp_path), client=ExplodingClient(), config=cfg)


def test_failed_reads_are_not_cached(tmp_path, cfg):
    client, doc = _client(cfg, {"orig": ("failed", {})})
    f = _pdf(tmp_path)
    read_invoice(f, client=client, config=cfg)
    read_invoice(f, client=client, config=cfg)
    assert len(doc.calls) == 2


def test_language_from_filename_and_manifest(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    assert read_invoice(_pdf(tmp_path, "inv_F_ta.pdf"), client=client, config=cfg).language == "ta-IN"
    (tmp_path / "languages.json").write_text(json.dumps({"bill7.pdf": "hi-IN"}), encoding="utf-8")
    assert read_invoice(_pdf(tmp_path, "bill7.pdf", b"%PDF other"), client=client, config=cfg).language == "hi-IN"


def test_language_detected_from_script(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("completed", result_with(
        vendor_name="ஸ்ரீ முருகன் ஹார்ட்வேர்ஸ்", amount_in_words="பன்னிரண்டாயிரத்து முன்னூற்று தொண்ணூறு"))})
    inv = read_invoice(_pdf(tmp_path, "x.pdf"), client=client, config=cfg)
    assert inv.language == "ta-IN"
    assert inv.vendor_key == "hrtvr mrkn"                    # same key as the English spelling
    assert inv.words_amount == Decimal("12390")


def test_privacy_full_account_never_in_repr_raw_native_or_artifacts(tmp_path, cfg):
    client, _ = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    full = "026291800001191"
    assert full not in repr(inv)
    assert inv.raw_native["account_number"] == "XXXX1191"
    art_file = Path(cfg.cache_dir) / "artifacts" / f"{inv.source_hash[:24]}.json"
    assert full not in art_file.read_text(encoding="utf-8")


def test_poll_timeout_returns_timeout_not_exception(tmp_path):
    cfg = ReadingConfig(cache_dir=tmp_path / "c", poll_interval_s=1, job_timeout_s=5)
    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s
    doc = FakeDocAi({"orig": ("completed", CLEAN_RESULT)}, polls_before_done=10_000)
    vc = VisionClient(FakeSdk(doc), config=cfg, sleep=sleep, clock=lambda: t["now"])
    out = vc.extract(_pdf(tmp_path))
    assert out.status == "timeout" and out.job_id


def test_config_refuses_advanced_mode(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"extract_mode": "advanced"}), encoding="utf-8")
    with pytest.raises(ValueError):
        ReadingConfig.load(p)


def test_serialize_round_trip_keeps_decimals_and_masks_account(tmp_path, cfg):
    from panch.reading.serialize import invoice_from_dict, invoice_to_dict
    client, _ = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    inv = read_invoice(_pdf(tmp_path), client=client, config=cfg)
    d = invoice_to_dict(inv)
    text = json.dumps(d, ensure_ascii=False)
    assert "026291800001191" not in text and d["total"] == "12390.00"
    back = invoice_from_dict(json.loads(text))
    assert back.total == inv.total and isinstance(back.total, Decimal)
    assert back.lines == inv.lines and back.date == inv.date and back.account_number is None


def test_read_folder_reads_supported_files_only(tmp_path, cfg):
    from panch.reading.reader import read_folder
    client, _ = _client(cfg, {"orig": ("completed", CLEAN_RESULT)})
    _pdf(tmp_path, "a.pdf", b"%PDF a")
    _pdf(tmp_path, "b.pdf", b"%PDF b")
    (tmp_path / "notes.txt").write_text("not an invoice", encoding="utf-8")
    invs = read_folder(tmp_path, config=cfg, client=client)
    assert len(invs) == 2 and len({i.id for i in invs}) == 2
