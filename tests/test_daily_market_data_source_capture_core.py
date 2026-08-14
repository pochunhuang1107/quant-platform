from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from research_sdk.daily_market_data_source_capture import (
    CA_SOURCE_MANIFEST_PATH,
    CAPTURE_MANIFEST_PATH,
    SOURCE_CAPTURE_IDENTITY_DOMAIN,
    SOURCE_CAPTURE_IDENTITY_VERSION,
    SOURCE_CAPTURE_MEMBER_PATHS,
    SOURCE_CAPTURE_REQUIRED_PATHS,
    DailyMarketDataSourceCaptureIdentityAuthority,
    DailyMarketDataSourceCaptureManifest,
    DailyMarketDataSourceCaptureMemberInput,
    DailyMarketDataSourceCapturePlanningError,
    DailyMarketDataSourceCaptureRole,
    DailyMarketDataSourceCaptureSerializationError,
    DailyMarketDataSourceCaptureVerificationError,
    canonical_source_capture_role_order,
    derive_daily_market_data_source_capture_id,
    parse_ca_source_manifest,
    parse_capture_manifest,
    plan_daily_market_data_source_capture,
    render_ca_source_manifest,
    render_capture_manifest,
    verify_daily_market_data_source_capture,
)
from research_sdk.daily_market_data_storage.serialization import sha256_bytes

BAR_BYTES = b'{"synthetic":"bars","symbol":"QQQ"}\n'
DIVIDEND_BYTES = b'{"synthetic":"dividends","symbol":"QQQ"}\n'
SPLIT_BYTES = b'{"synthetic":"splits","symbol":"QQQ"}\n'
OBSERVED_AT = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
GOLDEN_CAPTURE_ID = (
    "daily-market-data-source-capture-v1-"
    "21b077f1fd7aa5087ab4f8324f18f052a96bf5105bb0cb747136da55fe36bf67"
)
GOLDEN_MEMBER_HASHES = {
    DailyMarketDataSourceCaptureRole.BAR_RESPONSE: (
        "sha256:0c8f00c2edf0d448cd67e5880f4bae0ea28411df18540a24f122cb61ca4ff5b8"
    ),
    DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: (
        "sha256:cb72cdd16758ecd22fab8ce317dcfc74af26f4749742ab408dbfca7acf70a550"
    ),
    DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: (
        "sha256:359a6146a651bf4f02a6405fb93edf6368d75d1823c4019630b5b5bcca620605"
    ),
}
GOLDEN_CA_MANIFEST_HASH = (
    "sha256:6850f46a73d00e8af24887924fd541cc6c24c00a23e97750e53d1a690599db61"
)
GOLDEN_CA_MANIFEST_SIZE = 1232
GOLDEN_CAPTURE_MANIFEST_HASH = (
    "sha256:b98597fff28c9392bb459d166bd392db9f7a1816bf219ca52a303397a7ff3eb8"
)


def test_planning_derives_member_hash_size_order_and_goldens() -> None:
    plan = sample_plan(members=tuple(reversed(sample_members())))

    assert plan.capture_id == GOLDEN_CAPTURE_ID
    assert tuple(member.role for member in plan.capture_manifest.members) == (
        canonical_source_capture_role_order()
    )
    assert tuple(member.role for member in plan.member_bytes) == (
        canonical_source_capture_role_order()
    )
    assert tuple(plan.as_file_map()) == (
        "bars.json",
        "dividends.json",
        "splits.json",
        "capture-manifest.json",
        "ca-source-manifest.json",
    )
    assert {
        member.role: member.content_sha256 for member in plan.capture_manifest.members
    } == GOLDEN_MEMBER_HASHES
    assert {
        member.role: member.size_bytes for member in plan.capture_manifest.members
    } == {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: len(BAR_BYTES),
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: len(DIVIDEND_BYTES),
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: len(SPLIT_BYTES),
    }
    assert plan.ca_source_content_hash == GOLDEN_CA_MANIFEST_HASH
    assert plan.ca_source_size_bytes == GOLDEN_CA_MANIFEST_SIZE
    assert sha256_bytes(plan.capture_manifest_bytes) == GOLDEN_CAPTURE_MANIFEST_HASH
    assert b"synthetic:DIVIDEND_RESPONSE:symbol=QQQ" in plan.ca_source_manifest_bytes
    assert b"synthetic:SPLIT_RESPONSE:symbol=QQQ" in plan.ca_source_manifest_bytes
    assert b"synthetic:BAR_RESPONSE:symbol=QQQ" not in plan.ca_source_manifest_bytes

    verified = verify_daily_market_data_source_capture(plan.as_file_map())
    assert verified.capture_id == plan.capture_id
    assert verified.ca_source_content_hash == plan.ca_source_content_hash
    assert verified.member_bytes[DailyMarketDataSourceCaptureRole.BAR_RESPONSE] == (
        BAR_BYTES
    )


def test_identity_is_deterministic_and_binds_observation_batch_and_member_bytes() -> (
    None
):
    base = sample_plan()

    assert sample_plan().capture_id == base.capture_id
    assert sample_plan(
        capture_observed_at=datetime(2026, 1, 6, 0, 1, tzinfo=UTC)
    ).capture_id != (base.capture_id)
    changed_batch = sample_plan(acquisition_batch_id="synthetic-batch-2026-01-07")
    assert changed_batch.capture_id != base.capture_id
    assert changed_batch.ca_source_content_hash != base.ca_source_content_hash
    assert sample_plan(
        bars=b'{"synthetic":"bars","symbol":"QQQ","v":2}\n'
    ).capture_id != (base.capture_id)
    assert (
        sample_plan(
            dividends=b'{"synthetic":"dividends","symbol":"QQQ","v":2}\n'
        ).capture_id
        != base.capture_id
    )
    assert sample_plan(
        splits=b'{"synthetic":"splits","symbol":"QQQ","v":2}\n'
    ).capture_id != (base.capture_id)


def test_ca_manifest_hash_excludes_capture_id_and_bar_response_authority() -> None:
    base = sample_plan()
    changed_bar = sample_plan(bars=b'{"synthetic":"bars","symbol":"QQQ","v":2}\n')
    changed_dividend = sample_plan(
        dividends=b'{"synthetic":"dividends","symbol":"QQQ","v":2}\n'
    )
    changed_split = sample_plan(splits=b'{"synthetic":"splits","symbol":"QQQ","v":2}\n')

    assert changed_bar.capture_id != base.capture_id
    assert changed_bar.ca_source_content_hash == base.ca_source_content_hash
    assert changed_bar.ca_source_manifest_bytes == base.ca_source_manifest_bytes
    assert b"capture_id" not in base.ca_source_manifest_bytes
    assert b"BAR_RESPONSE" not in base.ca_source_manifest_bytes
    assert changed_dividend.ca_source_content_hash != base.ca_source_content_hash
    assert changed_split.ca_source_content_hash != base.ca_source_content_hash


def test_ca_source_reference_binding_distinguishes_capture_and_evidence_identity() -> (
    None
):
    base = sample_plan()
    changed_bar_reference = sample_plan(
        member_overrides={
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "source_reference_suffix": "changed-bar-reference"
            }
        }
    )
    changed_dividend_reference = sample_plan(
        member_overrides={
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: {
                "source_reference_suffix": "changed-dividend-reference"
            }
        }
    )
    changed_split_reference = sample_plan(
        member_overrides={
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: {
                "source_reference_suffix": "changed-split-reference"
            }
        }
    )

    assert changed_bar_reference.capture_id == base.capture_id
    assert (
        changed_bar_reference.ca_source_manifest_bytes == base.ca_source_manifest_bytes
    )
    assert changed_bar_reference.ca_source_content_hash == base.ca_source_content_hash

    assert changed_dividend_reference.capture_id == base.capture_id
    assert changed_dividend_reference.ca_source_manifest_bytes != (
        base.ca_source_manifest_bytes
    )
    assert changed_dividend_reference.ca_source_content_hash != (
        base.ca_source_content_hash
    )

    assert changed_split_reference.capture_id == base.capture_id
    assert changed_split_reference.ca_source_manifest_bytes != (
        base.ca_source_manifest_bytes
    )
    assert changed_split_reference.ca_source_content_hash != base.ca_source_content_hash


def test_ca_manifest_byte_authority_binds_only_dividend_and_split_content() -> None:
    base = sample_plan()
    changed_bar = sample_plan(bars=b'{"synthetic":"bars","symbol":"QQQ","v":2}\n')
    changed_dividend = sample_plan(
        dividends=b'{"synthetic":"dividends","symbol":"QQQ","v":2}\n'
    )
    changed_split = sample_plan(splits=b'{"synthetic":"splits","symbol":"QQQ","v":2}\n')

    assert changed_bar.capture_id != base.capture_id
    assert changed_bar.ca_source_manifest_bytes == base.ca_source_manifest_bytes
    assert changed_bar.ca_source_content_hash == base.ca_source_content_hash

    assert changed_dividend.capture_id != base.capture_id
    assert changed_dividend.ca_source_content_hash != base.ca_source_content_hash

    assert changed_split.capture_id != base.capture_id
    assert changed_split.ca_source_content_hash != base.ca_source_content_hash


def test_ca_member_authority_rejects_bar_response() -> None:
    bar_metadata = sample_plan().capture_manifest.members[0]

    with pytest.raises(ValueError, match="dividend/split"):
        bar_metadata.ca_source_authority()


def test_source_capture_member_paths_are_runtime_immutable() -> None:
    assert tuple(SOURCE_CAPTURE_REQUIRED_PATHS) == (
        "bars.json",
        "dividends.json",
        "splits.json",
        "capture-manifest.json",
        "ca-source-manifest.json",
    )

    with pytest.raises(TypeError):
        SOURCE_CAPTURE_MEMBER_PATHS[DailyMarketDataSourceCaptureRole.BAR_RESPONSE] = (
            "changed.json"  # type: ignore[index]
        )

    assert SOURCE_CAPTURE_MEMBER_PATHS[
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE
    ] == ("bars.json")


def test_evidence_only_fields_do_not_change_capture_identity() -> None:
    base = sample_plan()

    changed_request_id = sample_plan(api_request_id="synthetic-request-id-2")
    changed_media_type = sample_plan(media_type="application/json; charset=utf-8")
    changed_member_limitations = sample_plan(
        member_limitations=("different synthetic limitation",)
    )
    assert changed_request_id.capture_id == base.capture_id
    assert changed_media_type.capture_id == base.capture_id
    assert changed_member_limitations.capture_id == base.capture_id
    assert sample_plan(capture_limitations=("different capture prose",)).capture_id == (
        base.capture_id
    )
    assert sample_plan(source_reference_suffix="changed-reference").capture_id == (
        base.capture_id
    )
    assert changed_request_id.ca_source_content_hash == base.ca_source_content_hash
    assert changed_media_type.ca_source_content_hash == base.ca_source_content_hash
    assert changed_member_limitations.ca_source_content_hash == (
        base.ca_source_content_hash
    )


def test_non_200_member_status_cannot_be_planned() -> None:
    with pytest.raises(ValueError, match="HTTP 200"):
        sample_plan(
            member_overrides={
                DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {"http_status": 500}
            }
        )


@pytest.mark.parametrize(
    ("members", "match"),
    [
        (
            lambda: tuple(
                member
                for member in sample_members()
                if member.role is not DailyMarketDataSourceCaptureRole.BAR_RESPONSE
            ),
            "missing required",
        ),
        (
            lambda: tuple(
                member
                for member in sample_members()
                if member.role is not DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE
            ),
            "missing required",
        ),
        (
            lambda: tuple(
                member
                for member in sample_members()
                if member.role is not DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE
            ),
            "missing required",
        ),
        (lambda: (*sample_members(), sample_members()[0]), "duplicate"),
        (
            lambda: (
                member_input(
                    "UNEXPECTED_RESPONSE",
                    b"unexpected\n",
                ),
                *sample_members()[1:],
            ),
            "unsupported",
        ),
    ],
)
def test_planning_rejects_missing_duplicate_and_unexpected_roles(
    members: Callable[[], tuple[DailyMarketDataSourceCaptureMemberInput, ...]],
    match: str,
) -> None:
    with pytest.raises(DailyMarketDataSourceCapturePlanningError, match=match):
        sample_plan(members=members())


@pytest.mark.parametrize(
    "overrides",
    [
        {"capture_observed_at": datetime(2026, 1, 6, 0, 0)},
        {"provider": ""},
        {"source_family": ""},
        {"instrument_id": ""},
        {"symbol": ""},
    ],
)
def test_planning_rejects_bad_capture_level_metadata(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        sample_plan(**overrides)


@pytest.mark.parametrize(
    "member_overrides",
    [
        {
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "request_parameters": (("apiKey", "synthetic"),)
            }
        },
        {
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "request_parameters": (("symbol", "QQQ"), ("SYMBOL", "QQQ"))
            }
        },
        {
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "sanitized_source_reference": "https://example.test/data?api_key=x"
            }
        },
        {
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "sanitized_source_reference": "/tmp/source.json"
            }
        },
        {
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE: {
                "media_type": "Bearer synthetic-token"
            }
        },
    ],
)
def test_planning_rejects_credential_bearing_member_metadata(
    member_overrides: dict[DailyMarketDataSourceCaptureRole, dict[str, object]],
) -> None:
    with pytest.raises(ValueError):
        sample_plan(member_overrides=member_overrides)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload.update(
            {"capture_format_version": "unsupported-format-v1"}
        ),
        lambda payload: payload["members"][0].update({"content_sha256": "bad"}),
        lambda payload: payload["members"][0].update({"size_bytes": 999}),
        lambda payload: payload.update(
            {"capture_id": "daily-market-data-source-capture-v1-" + "a" * 64}
        ),
        lambda payload: payload["ca_source_manifest"].update(
            {"content_sha256": "sha256:" + "b" * 64}
        ),
        lambda payload: payload["ca_source_manifest"].update({"size_bytes": 999}),
    ],
)
def test_verifier_rejects_corrupt_capture_manifest(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    files = sample_plan().as_file_map()
    files[CAPTURE_MANIFEST_PATH] = _mutated_json(files[CAPTURE_MANIFEST_PATH], mutate)

    with pytest.raises(DailyMarketDataSourceCaptureVerificationError):
        verify_daily_market_data_source_capture(files)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload.update({"domain": "unsupported-domain"}),
        lambda payload: payload.update({"manifest_version": "unsupported-version"}),
        lambda payload: payload["members"][0].update(
            {"content_sha256": "sha256:" + "c" * 64}
        ),
    ],
)
def test_verifier_rejects_corrupt_ca_source_manifest(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    files = sample_plan().as_file_map()
    files[CA_SOURCE_MANIFEST_PATH] = _mutated_json(
        files[CA_SOURCE_MANIFEST_PATH], mutate
    )

    with pytest.raises(DailyMarketDataSourceCaptureVerificationError):
        verify_daily_market_data_source_capture(files)


def test_verifier_rejects_ca_source_reference_tampering() -> None:
    files = sample_plan().as_file_map()
    files[CA_SOURCE_MANIFEST_PATH] = _mutated_json(
        files[CA_SOURCE_MANIFEST_PATH],
        lambda payload: payload["members"][0].update(  # type: ignore[index]
            {"sanitized_source_reference": "synthetic:DIVIDEND_RESPONSE:tampered"}
        ),
    )

    with pytest.raises(DailyMarketDataSourceCaptureVerificationError):
        verify_daily_market_data_source_capture(files)


def test_verifier_rejects_coherent_ca_source_reference_tampering() -> None:
    files = sample_plan().as_file_map()
    files[CA_SOURCE_MANIFEST_PATH] = _mutated_json(
        files[CA_SOURCE_MANIFEST_PATH],
        lambda payload: payload["members"][0].update(  # type: ignore[index]
            {"sanitized_source_reference": "synthetic:DIVIDEND_RESPONSE:tampered"}
        ),
    )
    mutated_ca_hash = sha256_bytes(files[CA_SOURCE_MANIFEST_PATH])
    mutated_ca_size = len(files[CA_SOURCE_MANIFEST_PATH])
    files[CAPTURE_MANIFEST_PATH] = _mutated_json(
        files[CAPTURE_MANIFEST_PATH],
        lambda payload: payload["ca_source_manifest"].update(  # type: ignore[index]
            {"content_sha256": mutated_ca_hash, "size_bytes": mutated_ca_size}
        ),
    )

    capture_manifest = parse_capture_manifest(files[CAPTURE_MANIFEST_PATH])
    assert capture_manifest.capture_id == derive_daily_market_data_source_capture_id(
        capture_manifest.identity_authority()
    )

    with pytest.raises(DailyMarketDataSourceCaptureVerificationError):
        verify_daily_market_data_source_capture(files)


def test_verifier_rejects_member_hash_and_size_mismatch() -> None:
    files = sample_plan().as_file_map()
    files["bars.json"] = files["bars.json"] + b"changed"

    with pytest.raises(DailyMarketDataSourceCaptureVerificationError, match="hash"):
        verify_daily_market_data_source_capture(files)

    files = sample_plan().as_file_map()
    files[CAPTURE_MANIFEST_PATH] = _mutated_json(
        files[CAPTURE_MANIFEST_PATH],
        lambda payload: _set_member_size_and_refresh_capture_id(
            payload,
            len(files["bars.json"]) + 1,
        ),
    )
    with pytest.raises(DailyMarketDataSourceCaptureVerificationError, match="size"):
        verify_daily_market_data_source_capture(files)


@pytest.mark.parametrize(
    "removed_path",
    ["bars.json", "dividends.json", "splits.json"],
)
def test_verifier_rejects_missing_member_file(removed_path: str) -> None:
    files = sample_plan().as_file_map()
    del files[removed_path]

    with pytest.raises(DailyMarketDataSourceCaptureVerificationError, match="missing"):
        verify_daily_market_data_source_capture(files)


def test_verifier_rejects_unexpected_file_and_bad_file_types() -> None:
    files = sample_plan().as_file_map()
    files["unexpected.json"] = b"{}\n"
    with pytest.raises(
        DailyMarketDataSourceCaptureVerificationError, match="unexpected"
    ):
        verify_daily_market_data_source_capture(files)

    files = sample_plan().as_file_map()
    files["bars.json"] = bytearray(files["bars.json"])  # type: ignore[assignment]
    with pytest.raises(DailyMarketDataSourceCaptureVerificationError, match="bytes"):
        verify_daily_market_data_source_capture(files)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("parser", "data"),
    [
        (parse_capture_manifest, b'{"capture_id":"a","capture_id":"b"}\n'),
        (parse_ca_source_manifest, b'{"domain":"a","domain":"b"}\n'),
    ],
)
def test_source_capture_parsers_reject_duplicate_json_keys(
    parser: Callable[[bytes], object],
    data: bytes,
) -> None:
    with pytest.raises(
        DailyMarketDataSourceCaptureSerializationError, match="duplicate"
    ):
        parser(data)


@pytest.mark.parametrize(
    "mutate_bytes",
    [
        lambda data: json.dumps(json.loads(data), indent=2).encode("utf-8") + b"\n",
        lambda data: _unsorted_json(data),
        lambda data: data.removesuffix(b"\n"),
        lambda data: data + b"\n",
    ],
)
def test_capture_manifest_parser_rejects_noncanonical_equivalent_bytes(
    mutate_bytes: Callable[[bytes], bytes],
) -> None:
    canonical = sample_plan().capture_manifest_bytes

    with pytest.raises(
        DailyMarketDataSourceCaptureSerializationError,
        match="canonical JSON bytes",
    ):
        parse_capture_manifest(mutate_bytes(canonical))


@pytest.mark.parametrize(
    "mutate_bytes",
    [
        lambda data: json.dumps(json.loads(data), indent=2).encode("utf-8") + b"\n",
        lambda data: _unsorted_json(data),
        lambda data: data.removesuffix(b"\n"),
        lambda data: data + b"\n",
    ],
)
def test_ca_source_manifest_parser_rejects_noncanonical_equivalent_bytes(
    mutate_bytes: Callable[[bytes], bytes],
) -> None:
    canonical = sample_plan().ca_source_manifest_bytes

    with pytest.raises(
        DailyMarketDataSourceCaptureSerializationError,
        match="canonical JSON bytes",
    ):
        parse_ca_source_manifest(mutate_bytes(canonical))


def test_source_capture_parsers_reject_nonstandard_json_constants() -> None:
    with pytest.raises(
        DailyMarketDataSourceCaptureSerializationError,
        match="non-standard JSON constant",
    ):
        parse_capture_manifest(b'{"capture_id":NaN}\n')


def test_manifest_rendering_uses_shared_canonical_contract_renderer() -> None:
    plan = sample_plan()

    assert render_capture_manifest(plan.capture_manifest) == plan.capture_manifest_bytes
    assert render_ca_source_manifest(plan.ca_source_manifest) == (
        plan.ca_source_manifest_bytes
    )


def test_identity_authority_rejects_unsupported_identity_version() -> None:
    authority = sample_plan().capture_manifest.identity_authority()

    with pytest.raises(ValueError, match="identity version"):
        DailyMarketDataSourceCaptureIdentityAuthority(
            **{
                **authority.model_dump(mode="python"),
                "domain": SOURCE_CAPTURE_IDENTITY_DOMAIN,
                "identity_version": "unsupported-source-capture-v1",
            }
        )
    with pytest.raises(ValueError, match="identity domain"):
        DailyMarketDataSourceCaptureIdentityAuthority(
            **{
                **authority.model_dump(mode="python"),
                "domain": "unsupported-domain",
                "identity_version": SOURCE_CAPTURE_IDENTITY_VERSION,
            }
        )


def sample_plan(**overrides: object):
    data = {
        "provider": "synthetic-provider",
        "source_family": "synthetic-source-family",
        "instrument_id": "instrument-us-etf-qqq-xnas",
        "symbol": "QQQ",
        "capture_observed_at": OBSERVED_AT,
        "acquisition_batch_id": "synthetic-batch-2026-01-06",
        "members": sample_members(
            bars=overrides.pop("bars", BAR_BYTES),
            dividends=overrides.pop("dividends", DIVIDEND_BYTES),
            splits=overrides.pop("splits", SPLIT_BYTES),
            api_request_id=overrides.pop("api_request_id", "synthetic-request-id"),
            media_type=overrides.pop("media_type", "application/json"),
            member_limitations=overrides.pop(
                "member_limitations",
                ("synthetic source bytes only",),
            ),
            source_reference_suffix=overrides.pop("source_reference_suffix", None),
            member_overrides=overrides.pop("member_overrides", None),
        ),
        "limitations": overrides.pop(
            "capture_limitations", ("synthetic capture only",)
        ),
    }
    data.update(overrides)
    return plan_daily_market_data_source_capture(**data)  # type: ignore[arg-type]


def sample_members(
    *,
    bars: bytes = BAR_BYTES,
    dividends: bytes = DIVIDEND_BYTES,
    splits: bytes = SPLIT_BYTES,
    api_request_id: str | None = "synthetic-request-id",
    media_type: str = "application/json",
    member_limitations: tuple[str, ...] = ("synthetic source bytes only",),
    source_reference_suffix: str | None = None,
    member_overrides: dict[DailyMarketDataSourceCaptureRole, dict[str, object]]
    | None = None,
) -> tuple[DailyMarketDataSourceCaptureMemberInput, ...]:
    overrides = member_overrides or {}
    bar_overrides = {
        "api_request_id": api_request_id,
        "media_type": media_type,
        "limitations": member_limitations,
        "source_reference_suffix": source_reference_suffix,
    }
    bar_overrides.update(
        overrides.get(DailyMarketDataSourceCaptureRole.BAR_RESPONSE, {})
    )
    dividend_overrides = {
        "api_request_id": api_request_id,
        "media_type": media_type,
        "limitations": member_limitations,
        "source_reference_suffix": source_reference_suffix,
    }
    dividend_overrides.update(
        overrides.get(DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE, {})
    )
    split_overrides = {
        "api_request_id": api_request_id,
        "media_type": media_type,
        "limitations": member_limitations,
        "source_reference_suffix": source_reference_suffix,
    }
    split_overrides.update(
        overrides.get(DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE, {})
    )
    return (
        member_input(
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            bars,
            **bar_overrides,
        ),
        member_input(
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            dividends,
            **dividend_overrides,
        ),
        member_input(
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            splits,
            **split_overrides,
        ),
    )


def member_input(
    role: DailyMarketDataSourceCaptureRole | str,
    content: bytes,
    **overrides: object,
) -> DailyMarketDataSourceCaptureMemberInput:
    role_value = (
        role.value if isinstance(role, DailyMarketDataSourceCaptureRole) else role
    )
    data = {
        "role": role,
        "endpoint_family": "synthetic-endpoint",
        "endpoint_version": "v1",
        "request_parameters": (("symbol", "QQQ"), ("limit", "10")),
        "requested_scope": (("to", "2024-12-31"), ("from", "2024-01-02")),
        "sanitized_source_reference": f"synthetic:{role_value}:symbol=QQQ",
        "content": content,
        "http_status": 200,
        "media_type": "application/json",
        "api_request_id": "synthetic-request-id",
        "limitations": ("synthetic source bytes only",),
    }
    suffix = overrides.pop("source_reference_suffix", None)
    if suffix is not None:
        data["sanitized_source_reference"] = f"synthetic:{role_value}:{suffix}"
    data.update(overrides)
    return DailyMarketDataSourceCaptureMemberInput(**data)  # type: ignore[arg-type]


def _mutated_json(data: bytes, mutate: Callable[[dict[str, object]], None]) -> bytes:
    payload = json.loads(data)
    mutate(payload)
    return _canonical_json(payload)


def _set_member_size_and_refresh_capture_id(
    payload: dict[str, object],
    size_bytes: int,
) -> None:
    payload["members"][0]["content_sha256"] = sha256_bytes(BAR_BYTES)  # type: ignore[index]
    payload["members"][0]["size_bytes"] = size_bytes  # type: ignore[index]
    manifest = DailyMarketDataSourceCaptureManifest.model_validate(payload)
    payload["capture_id"] = derive_daily_market_data_source_capture_id(
        manifest.identity_authority()
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


def _unsorted_json(data: bytes) -> bytes:
    payload = json.loads(data)
    unsorted_payload = dict(reversed(tuple(payload.items())))
    return (
        json.dumps(
            unsorted_payload,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
