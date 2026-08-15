from __future__ import annotations

import errno
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

import research_sdk.daily_market_data_source_capture.local as local_storage
from research_sdk.daily_market_data_source_capture import (
    CA_SOURCE_MANIFEST_PATH,
    CAPTURE_MANIFEST_PATH,
    SOURCE_CAPTURE_REQUIRED_PATHS,
    DailyMarketDataSourceCaptureConflictError,
    DailyMarketDataSourceCaptureDiskVerificationError,
    DailyMarketDataSourceCaptureMemberInput,
    DailyMarketDataSourceCapturePathError,
    DailyMarketDataSourceCapturePublicationError,
    DailyMarketDataSourceCaptureRole,
    LocalDailyMarketDataSourceCapturePublicationStatus,
    PlannedDailyMarketDataSourceCapture,
    load_local_daily_market_data_source_capture,
    plan_daily_market_data_source_capture,
    publish_local_daily_market_data_source_capture,
    verify_daily_market_data_source_capture,
)

BAR_BYTES = b'{"synthetic":"bars","symbol":"QQQ"}\n'
DIVIDEND_BYTES = b'{"synthetic":"dividends","symbol":"QQQ"}\n'
SPLIT_BYTES = b'{"synthetic":"splits","symbol":"QQQ"}\n'
OBSERVED_AT = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
SOURCE_CAPTURE_DIR = "daily-market-data-source-captures"
EXPECTED_CAPTURE_FILES = SOURCE_CAPTURE_REQUIRED_PATHS


def test_publish_valid_plan_to_empty_root(tmp_path: Path) -> None:
    plan = sample_plan()
    root = tmp_path / "source-captures"

    result = publish_local_daily_market_data_source_capture(
        source_capture_root=root,
        plan=plan,
    )

    final_path = root / SOURCE_CAPTURE_DIR / plan.capture_id
    assert result.status is LocalDailyMarketDataSourceCapturePublicationStatus.CREATED
    assert result.capture_id == plan.capture_id
    assert result.path == final_path.resolve()
    assert result.verified.capture_id == plan.capture_id
    assert {path.name for path in final_path.iterdir()} == set(EXPECTED_CAPTURE_FILES)
    assert _read_capture_files(final_path) == plan.as_file_map()
    assert (
        load_local_daily_market_data_source_capture(
            source_capture_root=root,
            capture_id=plan.capture_id,
        ).capture_id
        == plan.capture_id
    )
    assert (
        result.verified.capture_manifest_bytes
        == (final_path / CAPTURE_MANIFEST_PATH).read_bytes()
    )
    assert (
        result.verified.ca_source_manifest_bytes
        == (final_path / CA_SOURCE_MANIFEST_PATH).read_bytes()
    )
    for role, relative_path in {
        DailyMarketDataSourceCaptureRole.BAR_RESPONSE: "bars.json",
        DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE: "dividends.json",
        DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE: "splits.json",
    }.items():
        assert (
            result.verified.member_bytes[role]
            == (final_path / relative_path).read_bytes()
        )
    for content in plan.as_file_map().values():
        assert str(tmp_path).encode() not in content


def test_publish_same_plan_twice_is_exact_byte_idempotent(tmp_path: Path) -> None:
    plan = sample_plan()

    first = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    hashes_before = _capture_hashes(first.path)
    second = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )

    assert first.status is LocalDailyMarketDataSourceCapturePublicationStatus.CREATED
    assert (
        second.status
        is LocalDailyMarketDataSourceCapturePublicationStatus.ALREADY_PRESENT
    )
    assert second.path == first.path
    assert _capture_hashes(first.path) == hashes_before
    assert {path.name for path in (tmp_path / SOURCE_CAPTURE_DIR).iterdir()} == {
        ".staging",
        plan.capture_id,
    }
    assert second.verified.capture_id == plan.capture_id


def test_evidence_only_request_id_plan_pair_has_same_identity_not_same_bytes() -> None:
    plan_a, plan_b = same_identity_different_evidence_plans()

    verified_a = verify_daily_market_data_source_capture(plan_a.as_file_map())
    verified_b = verify_daily_market_data_source_capture(plan_b.as_file_map())

    assert verified_a.capture_id == plan_a.capture_id
    assert verified_b.capture_id == plan_b.capture_id
    assert plan_a.capture_id == plan_b.capture_id
    assert plan_a.capture_manifest_bytes != plan_b.capture_manifest_bytes
    assert plan_a.ca_source_manifest_bytes == plan_b.ca_source_manifest_bytes
    assert _raw_member_files(plan_a) == _raw_member_files(plan_b)


def test_same_capture_id_with_different_exact_manifest_conflicts(
    tmp_path: Path,
) -> None:
    plan_a, plan_b = same_identity_different_evidence_plans()
    first = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan_a,
    )

    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan_b,
        )

    assert _read_capture_files(first.path) == plan_a.as_file_map()


def test_same_id_valid_existing_capture_conflict_reads_each_file_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_a, plan_b = same_identity_different_evidence_plans()
    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan_a,
    )
    reads: list[Path] = []
    original = local_storage._read_authoritative_file

    def record_final_read(file_path: Path) -> bytes:
        if file_path.parent == result.path:
            reads.append(file_path)
        return original(file_path)

    monkeypatch.setattr(local_storage, "_read_authoritative_file", record_final_read)

    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan_b,
        )

    assert [path.name for path in reads] == list(EXPECTED_CAPTURE_FILES)
    assert len(reads) == len(EXPECTED_CAPTURE_FILES)


def test_different_storage_root_does_not_change_source_authority(
    tmp_path: Path,
) -> None:
    plan = sample_plan()
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"

    result_a = publish_local_daily_market_data_source_capture(
        source_capture_root=root_a,
        plan=plan,
    )
    result_b = publish_local_daily_market_data_source_capture(
        source_capture_root=root_b,
        plan=plan,
    )

    assert result_a.path != result_b.path
    assert result_a.capture_id == result_b.capture_id == plan.capture_id
    assert _read_capture_files(result_a.path) == _read_capture_files(result_b.path)
    assert result_a.verified.capture_manifest_bytes == (
        result_b.verified.capture_manifest_bytes
    )
    assert result_a.verified.ca_source_manifest_bytes == (
        result_b.verified.ca_source_manifest_bytes
    )


def test_invalid_plan_causes_zero_filesystem_mutation(tmp_path: Path) -> None:
    plan = sample_plan()
    bad_plan = replace(
        plan,
        capture_id="daily-market-data-source-capture-v1-" + "0" * 64,
    )
    root = tmp_path / "source-captures"

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root,
            plan=bad_plan,
        )

    assert not root.exists()


def test_plan_file_map_is_called_once(tmp_path: Path) -> None:
    plan = sample_plan()
    calls = 0

    class SingleUsePlan:
        capture_id = plan.capture_id

        def as_file_map(self) -> dict[str, bytes]:
            nonlocal calls
            calls += 1
            if calls > 1:
                raise AssertionError("as_file_map called more than once")
            return plan.as_file_map()

    publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=SingleUsePlan(),  # type: ignore[arg-type]
    )

    assert calls == 1


def test_public_load_reads_each_authoritative_file_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    reads: list[Path] = []
    original = local_storage._read_authoritative_file

    def record_read(file_path: Path) -> bytes:
        reads.append(file_path)
        return original(file_path)

    monkeypatch.setattr(local_storage, "_read_authoritative_file", record_read)

    verified = load_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        capture_id=plan.capture_id,
    )

    assert verified.capture_id == plan.capture_id
    assert [path.name for path in reads] == list(EXPECTED_CAPTURE_FILES)
    assert len(reads) == len(EXPECTED_CAPTURE_FILES)
    assert (
        verified.capture_manifest_bytes
        == (result.path / CAPTURE_MANIFEST_PATH).read_bytes()
    )
    assert (
        verified.ca_source_manifest_bytes
        == (result.path / CA_SOURCE_MANIFEST_PATH).read_bytes()
    )


def test_already_present_publication_reads_existing_capture_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    reads: list[Path] = []
    original = local_storage._read_authoritative_file

    def record_read(file_path: Path) -> bytes:
        reads.append(file_path)
        return original(file_path)

    monkeypatch.setattr(local_storage, "_read_authoritative_file", record_read)

    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )

    assert (
        result.status
        is LocalDailyMarketDataSourceCapturePublicationStatus.ALREADY_PRESENT
    )
    assert [path.name for path in reads] == list(EXPECTED_CAPTURE_FILES)
    assert len(reads) == len(EXPECTED_CAPTURE_FILES)


@pytest.mark.parametrize("relative_path", EXPECTED_CAPTURE_FILES)
def test_existing_authoritative_file_mutation_is_conflict(
    tmp_path: Path,
    relative_path: str,
) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    target = result.path / relative_path
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert target.read_bytes().endswith(b" ")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda path: (path / "bars.json").unlink(),
        lambda path: (path / "extra.json").write_bytes(b"{}\n"),
        lambda path: (path / ".DS_Store").write_bytes(b"metadata"),
        lambda path: (path / "nested").mkdir(),
    ],
)
def test_file_set_mismatch_fails_load_as_disk_error_and_republish_as_conflict(
    tmp_path: Path,
    mutate: Callable[[Path], object],
) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    mutate(result.path)

    with pytest.raises(DailyMarketDataSourceCaptureDiskVerificationError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=plan.capture_id,
        )
    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )


def test_final_path_existing_as_empty_directory_file_or_symlink_is_conflict(
    tmp_path: Path,
) -> None:
    _require_symlink_support(tmp_path)
    plan = sample_plan()

    root = tmp_path / "empty-dir-root"
    final_path = root / SOURCE_CAPTURE_DIR / plan.capture_id
    final_path.mkdir(parents=True)
    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root,
            plan=plan,
        )

    root_file = tmp_path / "file-root"
    data_root = root_file / SOURCE_CAPTURE_DIR
    data_root.mkdir(parents=True)
    (data_root / plan.capture_id).write_text("not a directory")
    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root_file,
            plan=plan,
        )

    root_link = tmp_path / "link-root"
    data_root_link = root_link / SOURCE_CAPTURE_DIR
    data_root_link.mkdir(parents=True)
    target = tmp_path / "final-target"
    target.mkdir()
    (data_root_link / plan.capture_id).symlink_to(
        target,
        target_is_directory=True,
    )
    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root_link,
            plan=plan,
        )


@pytest.mark.parametrize(
    "capture_id",
    [
        "../../escape",
        "/absolute/path",
        "foo/bar",
        r"foo\bar",
        ".",
        "..",
        "daily-market-data-source-capture-v1-not-a-hash",
        "daily-market-data-source-capture-v1-" + "A" * 64,
    ],
)
def test_local_loader_rejects_capture_id_traversal(
    tmp_path: Path,
    capture_id: str,
) -> None:
    tmp_path.mkdir(exist_ok=True)

    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=capture_id,
        )


def test_direct_load_missing_file_and_symlink_final_path_are_path_errors(
    tmp_path: Path,
) -> None:
    _require_symlink_support(tmp_path)
    plan = sample_plan()
    data_root = tmp_path / SOURCE_CAPTURE_DIR
    data_root.mkdir()

    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=plan.capture_id,
        )

    target = tmp_path / "target"
    target.mkdir()
    (data_root / plan.capture_id).symlink_to(target, target_is_directory=True)
    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=plan.capture_id,
        )


def test_authoritative_file_symlink_fails_load_and_republish(
    tmp_path: Path,
) -> None:
    _require_symlink_support(tmp_path)
    plan = sample_plan()
    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    (result.path / "bars.json").unlink()
    symlink_target = tmp_path / "linked-bars.json"
    symlink_target.write_bytes(BAR_BYTES)
    (result.path / "bars.json").symlink_to(symlink_target)

    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=plan.capture_id,
        )
    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )


def test_directory_instead_of_authoritative_file_fails_closed(tmp_path: Path) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )
    (result.path / "bars.json").unlink()
    (result.path / "bars.json").mkdir()

    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=plan.capture_id,
        )
    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )


def test_symlinked_managed_paths_fail_closed(tmp_path: Path) -> None:
    _require_symlink_support(tmp_path)
    plan = sample_plan()

    actual_root = tmp_path / "actual-root"
    actual_root.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(actual_root, target_is_directory=True)
    with pytest.raises(DailyMarketDataSourceCapturePathError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root_link,
            plan=plan,
        )

    root = tmp_path / "root"
    root.mkdir()
    managed_target = tmp_path / "managed-target"
    managed_target.mkdir()
    (root / SOURCE_CAPTURE_DIR).symlink_to(managed_target, target_is_directory=True)
    with pytest.raises(DailyMarketDataSourceCapturePathError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root,
            plan=plan,
        )

    root2 = tmp_path / "root2"
    data_root = root2 / SOURCE_CAPTURE_DIR
    data_root.mkdir(parents=True)
    staging_target = tmp_path / "staging-target"
    staging_target.mkdir()
    (data_root / ".staging").symlink_to(staging_target, target_is_directory=True)
    with pytest.raises(DailyMarketDataSourceCapturePathError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=root2,
            plan=plan,
        )


def test_staging_namespace_is_not_authoritative_and_unrelated_child_remains(
    tmp_path: Path,
) -> None:
    plan = sample_plan()
    staging_root = tmp_path / SOURCE_CAPTURE_DIR / ".staging"
    unrelated = staging_root / "manual-orphan"
    unrelated.mkdir(parents=True)

    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )

    assert result.status is LocalDailyMarketDataSourceCapturePublicationStatus.CREATED
    assert unrelated.exists()
    assert {path.name for path in result.path.iterdir()} == set(EXPECTED_CAPTURE_FILES)


def test_staging_write_failure_cleans_only_invocation_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    staging_root = tmp_path / SOURCE_CAPTURE_DIR / ".staging"
    unrelated = staging_root / "unrelated"
    unrelated.mkdir(parents=True)

    def fail_mid_write(
        *,
        staging_path: Path,
        planned_files: dict[str, bytes],
    ) -> None:
        (staging_path / "bars.json").write_bytes(planned_files["bars.json"])
        raise DailyMarketDataSourceCapturePublicationError("simulated write failure")

    monkeypatch.setattr(local_storage, "_write_planned_files", fail_mid_write)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).exists()
    assert unrelated.exists()
    assert list(staging_root.iterdir()) == [unrelated]


def test_file_fsync_failure_before_rename_cleans_invocation_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    staging_root = tmp_path / SOURCE_CAPTURE_DIR / ".staging"
    unrelated = staging_root / "unrelated"
    unrelated.mkdir(parents=True)

    def fail_file_fsync(descriptor: int) -> None:
        raise OSError(errno.EIO, "simulated file fsync failure")

    monkeypatch.setattr(local_storage.os, "fsync", fail_file_fsync)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).exists()
    assert unrelated.exists()
    assert list(staging_root.iterdir()) == [unrelated]


def test_directory_fsync_helpers_follow_repository_portability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_open(path: Path, flags: int) -> int:
        raise OSError(errno.EINVAL, "directory fsync unsupported")

    monkeypatch.setattr(local_storage.os, "open", unsupported_open)

    local_storage._fsync_directory(tmp_path)


def test_unsupported_directory_fsync_after_open_closes_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_descriptors: list[int] = []

    def open_directory(path: Path, flags: int) -> int:
        return 123

    def unsupported_fsync(descriptor: int) -> None:
        raise OSError(errno.EINVAL, "directory fsync unsupported")

    def close_descriptor(descriptor: int) -> None:
        closed_descriptors.append(descriptor)

    monkeypatch.setattr(local_storage.os, "open", open_directory)
    monkeypatch.setattr(local_storage.os, "fsync", unsupported_fsync)
    monkeypatch.setattr(local_storage.os, "close", close_descriptor)

    local_storage._fsync_directory(tmp_path)

    assert closed_descriptors == [123]


def test_directory_fsync_failure_before_rename_fails_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_directory_fsync(directory: Path) -> None:
        raise OSError(errno.EIO, "simulated directory fsync failure")

    monkeypatch.setattr(local_storage, "_fsync_directory", fail_directory_fsync)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).exists()


def test_parent_fsync_failure_after_rename_leaves_final_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    fsync_calls = 0

    def fail_parent_fsync(directory: Path) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError(errno.EIO, "simulated parent fsync failure")

    monkeypatch.setattr(local_storage, "_fsync_directory", fail_parent_fsync)

    with pytest.raises(DailyMarketDataSourceCaptureDiskVerificationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).is_dir()


def test_fsync_helpers_are_invoked_for_files_and_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    fsync_calls = 0
    directory_fsyncs: list[Path] = []

    def record_file_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1

    def record_directory_fsync(directory: Path) -> None:
        directory_fsyncs.append(directory)

    monkeypatch.setattr(local_storage.os, "fsync", record_file_fsync)
    monkeypatch.setattr(local_storage, "_fsync_directory", record_directory_fsync)

    publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )

    assert fsync_calls == len(EXPECTED_CAPTURE_FILES)
    assert directory_fsyncs == [
        tmp_path.resolve() / SOURCE_CAPTURE_DIR / ".staging" / directory_fsyncs[0].name,
        tmp_path.resolve() / SOURCE_CAPTURE_DIR,
    ]


def test_staged_verification_failure_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_staging_verification(**_: object) -> None:
        raise DailyMarketDataSourceCapturePublicationError(
            "simulated staging verification"
        )

    monkeypatch.setattr(
        local_storage,
        "_verify_staged_or_final_bytes",
        fail_staging_verification,
    )

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).exists()
    assert list((tmp_path / SOURCE_CAPTURE_DIR / ".staging").iterdir()) == []


def test_staged_exact_byte_mismatch_fails_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    rename_called = False
    write_planned_files = local_storage._write_planned_files

    def mutate_after_write(
        *,
        staging_path: Path,
        planned_files: dict[str, bytes],
    ) -> None:
        write_planned_files(staging_path=staging_path, planned_files=planned_files)
        (staging_path / "bars.json").write_bytes(planned_files["bars.json"] + b" ")

    def record_rename(source: Path, destination: Path) -> None:
        nonlocal rename_called
        rename_called = True

    monkeypatch.setattr(local_storage, "_write_planned_files", mutate_after_write)
    monkeypatch.setattr(local_storage, "_rename_directory", record_rename)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert not rename_called
    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).exists()


def test_staged_semantically_valid_same_id_mismatch_fails_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_a, plan_b = same_identity_different_evidence_plans()
    rename_called = False
    write_planned_files = local_storage._write_planned_files

    def write_valid_same_id_mismatch(
        *,
        staging_path: Path,
        planned_files: dict[str, bytes],
    ) -> None:
        write_planned_files(staging_path=staging_path, planned_files=planned_files)
        (staging_path / CAPTURE_MANIFEST_PATH).write_bytes(
            plan_b.capture_manifest_bytes
        )
        verified = verify_daily_market_data_source_capture(
            _read_capture_files(staging_path)
        )
        assert verified.capture_id == plan_a.capture_id

    def record_rename(source: Path, destination: Path) -> None:
        nonlocal rename_called
        rename_called = True

    monkeypatch.setattr(
        local_storage,
        "_write_planned_files",
        write_valid_same_id_mismatch,
    )
    monkeypatch.setattr(local_storage, "_rename_directory", record_rename)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan_a,
        )

    assert not rename_called
    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan_a.capture_id).exists()


def test_same_id_rename_race_returns_already_present_for_exact_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def race_with_identical_final(source: Path, destination: Path) -> None:
        destination.mkdir()
        _write_capture_files(destination, plan.as_file_map())
        raise OSError(errno.ENOTEMPTY, "destination exists")

    monkeypatch.setattr(local_storage, "_rename_directory", race_with_identical_final)

    result = publish_local_daily_market_data_source_capture(
        source_capture_root=tmp_path,
        plan=plan,
    )

    assert (
        result.status
        is LocalDailyMarketDataSourceCapturePublicationStatus.ALREADY_PRESENT
    )
    assert _read_capture_files(result.path) == plan.as_file_map()
    assert list((tmp_path / SOURCE_CAPTURE_DIR / ".staging").iterdir()) == []


def test_destination_race_with_valid_same_id_different_bytes_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_a, plan_b = same_identity_different_evidence_plans()
    final_path = tmp_path / SOURCE_CAPTURE_DIR / plan_a.capture_id
    final_reads: list[Path] = []
    original_read = local_storage._read_authoritative_file

    def record_final_read(file_path: Path) -> bytes:
        if file_path.parent == final_path.resolve():
            final_reads.append(file_path)
        return original_read(file_path)

    def race_with_valid_same_id_final(source: Path, destination: Path) -> None:
        destination.mkdir()
        _write_capture_files(destination, plan_b.as_file_map())
        assert (
            verify_daily_market_data_source_capture(
                _read_capture_files(destination)
            ).capture_id
            == plan_a.capture_id
        )
        raise OSError(errno.ENOTEMPTY, "destination exists")

    monkeypatch.setattr(local_storage, "_read_authoritative_file", record_final_read)
    monkeypatch.setattr(
        local_storage,
        "_rename_directory",
        race_with_valid_same_id_final,
    )

    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan_a,
        )

    assert _read_capture_files(final_path) == plan_b.as_file_map()
    assert list((tmp_path / SOURCE_CAPTURE_DIR / ".staging").iterdir()) == []
    assert [path.name for path in final_reads] == list(EXPECTED_CAPTURE_FILES)
    assert len(final_reads) == len(EXPECTED_CAPTURE_FILES)


def test_destination_race_cleanup_failure_is_visible_for_already_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def race_with_identical_final(source: Path, destination: Path) -> None:
        destination.mkdir()
        _write_capture_files(destination, plan.as_file_map())
        raise OSError(errno.ENOTEMPTY, "destination exists")

    def fail_cleanup(staging_path: Path) -> None:
        raise OSError(errno.EIO, "cleanup failed")

    monkeypatch.setattr(local_storage, "_rename_directory", race_with_identical_final)
    monkeypatch.setattr(local_storage, "_cleanup_staging_best_effort", fail_cleanup)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError) as exc_info:
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert isinstance(exc_info.value.__cause__, OSError)
    final_path = tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id
    assert _read_capture_files(final_path) == plan.as_file_map()


def test_same_id_rename_race_with_conflicting_capture_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def race_with_conflicting_final(source: Path, destination: Path) -> None:
        files = plan.as_file_map()
        files["bars.json"] = files["bars.json"] + b" "
        destination.mkdir()
        _write_capture_files(destination, files)
        raise OSError(errno.ENOTEMPTY, "destination exists")

    monkeypatch.setattr(local_storage, "_rename_directory", race_with_conflicting_final)

    with pytest.raises(DailyMarketDataSourceCaptureConflictError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert list((tmp_path / SOURCE_CAPTURE_DIR / ".staging").iterdir()) == []


@pytest.mark.parametrize(
    "rename_error",
    [
        OSError(errno.EXDEV, "cross-device link"),
        PermissionError(errno.EACCES, "permission denied"),
    ],
)
def test_unexpected_rename_errors_fail_without_copy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rename_error: OSError,
) -> None:
    plan = sample_plan()

    def fail_rename(source: Path, destination: Path) -> None:
        raise rename_error

    monkeypatch.setattr(local_storage, "_rename_directory", fail_rename)

    with pytest.raises(DailyMarketDataSourceCapturePublicationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert not (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).exists()
    assert list((tmp_path / SOURCE_CAPTURE_DIR / ".staging").iterdir()) == []


def test_post_rename_final_verification_failure_leaves_final_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_final_load(**_: object) -> object:
        raise DailyMarketDataSourceCaptureDiskVerificationError(
            "simulated final failure"
        )

    monkeypatch.setattr(
        local_storage,
        "_load_local_source_capture_files_and_verify",
        fail_final_load,
    )

    with pytest.raises(DailyMarketDataSourceCaptureDiskVerificationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).is_dir()


def test_final_semantically_valid_same_id_mismatch_after_rename_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_a, plan_b = same_identity_different_evidence_plans()
    rename_directory = local_storage._rename_directory

    def rename_then_swap_valid_manifest(source: Path, destination: Path) -> None:
        rename_directory(source, destination)
        (destination / CAPTURE_MANIFEST_PATH).write_bytes(plan_b.capture_manifest_bytes)
        verified = verify_daily_market_data_source_capture(
            _read_capture_files(destination)
        )
        assert verified.capture_id == plan_a.capture_id

    monkeypatch.setattr(
        local_storage,
        "_rename_directory",
        rename_then_swap_valid_manifest,
    )

    with pytest.raises(DailyMarketDataSourceCaptureDiskVerificationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan_a,
        )

    final_path = tmp_path / SOURCE_CAPTURE_DIR / plan_a.capture_id
    assert final_path.is_dir()
    assert (final_path / CAPTURE_MANIFEST_PATH).read_bytes() == (
        plan_b.capture_manifest_bytes
    )
    assert (
        verify_daily_market_data_source_capture(
            _read_capture_files(final_path)
        ).capture_id
        == plan_a.capture_id
    )


def test_final_exact_byte_mismatch_after_rename_fails_and_leaves_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    original_load = local_storage._load_local_source_capture_files_and_verify
    load_calls = 0

    def corrupt_before_final_load(**kwargs: object) -> object:
        nonlocal load_calls
        load_calls += 1
        root = Path(kwargs["source_capture_root"])
        if load_calls == 1:
            final = root / SOURCE_CAPTURE_DIR / plan.capture_id / "bars.json"
            final.write_bytes(final.read_bytes() + b" ")
        return original_load(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        local_storage,
        "_load_local_source_capture_files_and_verify",
        corrupt_before_final_load,
    )

    with pytest.raises(DailyMarketDataSourceCaptureDiskVerificationError):
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert (tmp_path / SOURCE_CAPTURE_DIR / plan.capture_id).is_dir()


def test_load_missing_root_is_read_only(tmp_path: Path) -> None:
    plan = sample_plan()
    missing_root = tmp_path / "missing-root"

    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=missing_root,
            capture_id=plan.capture_id,
        )

    assert not missing_root.exists()


def test_direct_load_regular_file_capture_path_is_path_error(
    tmp_path: Path,
) -> None:
    plan = sample_plan()
    data_root = tmp_path / SOURCE_CAPTURE_DIR
    data_root.mkdir()
    final_path = data_root / plan.capture_id
    final_path.write_text("not a directory")

    with pytest.raises(DailyMarketDataSourceCapturePathError):
        load_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            capture_id=plan.capture_id,
        )

    assert final_path.is_file()


def test_staging_cleanup_primary_error_keeps_cleanup_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_write(**_: object) -> None:
        raise DailyMarketDataSourceCapturePublicationError("primary failure")

    def fail_cleanup(staging_path: Path) -> None:
        raise OSError(errno.EIO, "cleanup failed")

    monkeypatch.setattr(local_storage, "_write_planned_files", fail_write)
    monkeypatch.setattr(local_storage, "_cleanup_staging_best_effort", fail_cleanup)

    with pytest.raises(
        DailyMarketDataSourceCapturePublicationError,
        match="primary failure",
    ) as exc_info:
        publish_local_daily_market_data_source_capture(
            source_capture_root=tmp_path,
            plan=plan,
        )

    assert "failed to clean staging directory" in "\n".join(
        getattr(exc_info.value, "__notes__", [])
    )


def sample_plan(
    *,
    api_request_id: str | None = "synthetic-request-id",
) -> PlannedDailyMarketDataSourceCapture:
    return plan_daily_market_data_source_capture(
        provider="synthetic-provider",
        source_family="synthetic-source-family",
        instrument_id="instrument-us-etf-qqq-xnas",
        symbol="QQQ",
        capture_observed_at=OBSERVED_AT,
        acquisition_batch_id="synthetic-batch-2026-01-06",
        members=sample_members(api_request_id=api_request_id),
        limitations=("synthetic capture only",),
    )


def same_identity_different_evidence_plans() -> tuple[
    PlannedDailyMarketDataSourceCapture,
    PlannedDailyMarketDataSourceCapture,
]:
    return (
        sample_plan(api_request_id="synthetic-request-a"),
        sample_plan(api_request_id="synthetic-request-b"),
    )


def sample_members(
    *,
    api_request_id: str | None = "synthetic-request-id",
) -> tuple[DailyMarketDataSourceCaptureMemberInput, ...]:
    return (
        member_input(
            DailyMarketDataSourceCaptureRole.BAR_RESPONSE,
            BAR_BYTES,
            api_request_id=api_request_id,
        ),
        member_input(
            DailyMarketDataSourceCaptureRole.DIVIDEND_RESPONSE,
            DIVIDEND_BYTES,
            api_request_id=api_request_id,
        ),
        member_input(
            DailyMarketDataSourceCaptureRole.SPLIT_RESPONSE,
            SPLIT_BYTES,
            api_request_id=api_request_id,
        ),
    )


def member_input(
    role: DailyMarketDataSourceCaptureRole,
    content: bytes,
    *,
    api_request_id: str | None = "synthetic-request-id",
) -> DailyMarketDataSourceCaptureMemberInput:
    return DailyMarketDataSourceCaptureMemberInput(
        role=role,
        endpoint_family="synthetic-endpoint",
        endpoint_version="v1",
        request_parameters=(("symbol", "QQQ"), ("limit", "10")),
        requested_scope=(("to", "2024-12-31"), ("from", "2024-01-02")),
        sanitized_source_reference=f"synthetic:{role.value}:symbol=QQQ",
        content=content,
        http_status=200,
        media_type="application/json",
        api_request_id=api_request_id,
        limitations=("synthetic source bytes only",),
    )


def _raw_member_files(
    plan: PlannedDailyMarketDataSourceCapture,
) -> dict[str, bytes]:
    files = plan.as_file_map()
    return {
        relative_path: files[relative_path]
        for relative_path in ("bars.json", "dividends.json", "splits.json")
    }


def _read_capture_files(directory: Path) -> dict[str, bytes]:
    return {
        relative_path: (directory / relative_path).read_bytes()
        for relative_path in EXPECTED_CAPTURE_FILES
    }


def _write_capture_files(directory: Path, files: dict[str, bytes]) -> None:
    for relative_path in EXPECTED_CAPTURE_FILES:
        (directory / relative_path).write_bytes(files[relative_path])


def _capture_hashes(directory: Path) -> dict[str, str]:
    return {
        relative_path: sha256((directory / relative_path).read_bytes()).hexdigest()
        for relative_path in EXPECTED_CAPTURE_FILES
    }


def _require_symlink_support(tmp_path: Path) -> None:
    target = tmp_path / "symlink-target"
    link = tmp_path / "symlink-link"
    target.write_text("target")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is not supported: {exc}")
