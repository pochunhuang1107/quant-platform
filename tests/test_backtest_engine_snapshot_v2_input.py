from __future__ import annotations

import inspect
import json
from hashlib import sha256

import pytest

import backtest_engine.snapshot_v2_input as snapshot_v2_input_module
from backtest_engine.snapshot_v2_input import (
    DailyMarketDataSnapshotV2InputError,
    load_daily_market_data_snapshot_v2,
)
from helpers_daily_market_data_snapshots import sample_plan
from helpers_daily_market_data_snapshots_v2 import sample_plan_v2
from research_sdk.daily_market_data_storage.serialization import (
    parse_canonical_daily_bars,
)
from research_sdk.daily_market_data_storage.verification_v2 import (
    verify_daily_market_data_snapshot_bundle_v2,
)


def test_valid_snapshot_v2_mapping_loads_verified_result_and_bars() -> None:
    files = sample_plan_v2().as_file_map()

    loaded = load_daily_market_data_snapshot_v2(files)
    verified = verify_daily_market_data_snapshot_bundle_v2(files)

    assert loaded.verified_snapshot == verified
    assert loaded.verified_snapshot.snapshot_id == verified.snapshot_id
    assert loaded.bars == parse_canonical_daily_bars(files["bars.jsonl"])


def test_loaded_bars_equal_canonical_bars_encoded_in_jsonl() -> None:
    files = sample_plan_v2().as_file_map()

    loaded = load_daily_market_data_snapshot_v2(files)

    assert loaded.bars == parse_canonical_daily_bars(files["bars.jsonl"])
    assert tuple(bar.session_date.isoformat() for bar in loaded.bars) == (
        "2026-01-02",
        "2026-01-05",
    )


def test_caller_dict_mutation_after_load_cannot_change_returned_bars() -> None:
    files = sample_plan_v2().as_file_map()
    loaded = load_daily_market_data_snapshot_v2(files)
    original_bars = loaded.bars
    original_snapshot_id = loaded.verified_snapshot.snapshot_id

    files.clear()

    assert loaded.bars == original_bars
    assert loaded.verified_snapshot.snapshot_id == original_snapshot_id


def test_caller_replacing_bars_after_load_cannot_change_loaded_result() -> None:
    files = sample_plan_v2().as_file_map()
    loaded = load_daily_market_data_snapshot_v2(files)
    original_bars = loaded.bars

    files["bars.jsonl"] = b"not-json\n"

    assert loaded.bars == original_bars
    assert loaded.verified_snapshot.snapshot_id != ""


def test_corrupt_bars_jsonl_fails() -> None:
    files = sample_plan_v2().as_file_map()
    files["bars.jsonl"] = b"not-json\n"

    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        load_daily_market_data_snapshot_v2(files)


def test_noncanonical_bars_bytes_fail() -> None:
    files = sample_plan_v2().as_file_map()
    files["bars.jsonl"] = (
        b'{"close":"101.5","high":"102","low":"100","open":"101",'
        b'"session_date":"2026-01-05","volume":1100}\n'
        b'{"close":"100.5","high":"101","low":"99","open":"100",'
        b'"session_date":"2026-01-02","volume":1000}\n'
    )
    _refresh_bundle_file_entry(files, "bars.jsonl")

    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        load_daily_market_data_snapshot_v2(files)


def test_swapped_bars_from_another_valid_bundle_fail() -> None:
    files = sample_plan_v2().as_file_map()
    other_files = sample_plan_v2(source_bytes=_alternate_bars_jsonl()).as_file_map()
    files["bars.jsonl"] = other_files["bars.jsonl"]

    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        load_daily_market_data_snapshot_v2(files)


def test_missing_file_fails() -> None:
    files = sample_plan_v2().as_file_map()
    del files["corporate-action-evidence.json"]

    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        load_daily_market_data_snapshot_v2(files)


def test_extra_file_fails() -> None:
    files = sample_plan_v2().as_file_map()
    files["unexpected.json"] = b"{}\n"

    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        load_daily_market_data_snapshot_v2(files)


def test_v1_bundle_fails() -> None:
    with pytest.raises(DailyMarketDataSnapshotV2InputError):
        load_daily_market_data_snapshot_v2(sample_plan().as_file_map())


def test_non_bytes_runtime_bundle_value_fails() -> None:
    files = sample_plan_v2().as_file_map()
    files["bars.jsonl"] = bytearray(files["bars.jsonl"])  # type: ignore[assignment]

    with pytest.raises(DailyMarketDataSnapshotV2InputError, match="string paths"):
        load_daily_market_data_snapshot_v2(files)  # type: ignore[arg-type]


def test_non_string_runtime_bundle_key_fails() -> None:
    files = sample_plan_v2().as_file_map()
    files[1] = files["bars.jsonl"]  # type: ignore[index]

    with pytest.raises(DailyMarketDataSnapshotV2InputError, match="string paths"):
        load_daily_market_data_snapshot_v2(files)  # type: ignore[arg-type]


def test_no_detached_bars_parameter_exists() -> None:
    signature = inspect.signature(load_daily_market_data_snapshot_v2)

    assert tuple(signature.parameters) == ("files",)


def test_loader_source_has_no_filesystem_or_network_access() -> None:
    source = inspect.getsource(snapshot_v2_input_module)

    for prohibited in (
        "datetime.now",
        "datetime.utcnow",
        "date.today",
        "time.time",
        "requests",
        "httpx",
        "urllib.request",
        "socket",
        "Path",
        "open(",
        "read_bytes",
        "write_bytes",
        "os.",
        "shutil",
        "tempfile",
    ):
        assert prohibited not in source


def _alternate_bars_jsonl() -> bytes:
    return (
        b'{"close":"200.5","high":"201","low":"199","open":"200",'
        b'"session_date":"2026-01-02","volume":2000}\n'
        b'{"close":"201.5","high":"202","low":"200","open":"201",'
        b'"session_date":"2026-01-05","volume":2100}\n'
    )


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _refresh_bundle_file_entry(files: dict[str, bytes], relative_path: str) -> None:
    manifest = json.loads(files["bundle-manifest.json"])
    for entry in manifest["files"]:
        if entry["relative_path"] == relative_path:
            entry["sha256"] = f"sha256:{sha256(files[relative_path]).hexdigest()}"
            entry["size_bytes"] = len(files[relative_path])
            break
    files["bundle-manifest.json"] = _canonical_json(manifest)
