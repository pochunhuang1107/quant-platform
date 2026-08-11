from __future__ import annotations

import errno
import shutil
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

import research_sdk.daily_market_data_storage.local as local_storage
from helpers_daily_market_data_snapshots import sample_plan
from research_sdk.daily_market_data_storage import (
    DailyMarketDataSnapshotConflictError,
    DailyMarketDataSnapshotDiskVerificationError,
    DailyMarketDataSnapshotPathError,
    DailyMarketDataSnapshotPublicationError,
    LocalDailyMarketDataSnapshotPublicationStatus,
    publish_local_daily_market_data_snapshot,
    verify_local_daily_market_data_snapshot,
)

EXPECTED_BUNDLE_FILES = (
    "bars.jsonl",
    "expected-sessions.json",
    "policy.json",
    "provenance.json",
    "quality-report.json",
    "snapshot-manifest.json",
    "bundle-manifest.json",
)


def test_publish_valid_plan_to_empty_root(tmp_path: Path) -> None:
    plan = sample_plan()
    root = tmp_path / "snapshots"

    result = publish_local_daily_market_data_snapshot(
        snapshot_root=root,
        plan=plan,
    )

    final_path = root / "daily-market-data" / plan.snapshot_id
    assert result.status is LocalDailyMarketDataSnapshotPublicationStatus.CREATED
    assert result.snapshot_id == plan.snapshot_id
    assert result.path == final_path.resolve()
    assert result.verified.snapshot_id == plan.snapshot_id
    assert set(path.name for path in final_path.iterdir()) == set(EXPECTED_BUNDLE_FILES)
    assert _read_bundle(final_path) == plan.as_file_map()
    assert (
        verify_local_daily_market_data_snapshot(
            snapshot_root=root,
            snapshot_id=plan.snapshot_id,
        ).snapshot_id
        == plan.snapshot_id
    )
    for content in plan.as_file_map().values():
        assert str(tmp_path).encode() not in content


def test_invalid_plan_causes_zero_filesystem_mutation(tmp_path: Path) -> None:
    plan = sample_plan()
    bad_plan = replace(plan, snapshot_id="daily-market-data-snapshot-v1-" + "0" * 64)
    root = tmp_path / "snapshots"

    with pytest.raises(DailyMarketDataSnapshotPublicationError):
        publish_local_daily_market_data_snapshot(snapshot_root=root, plan=bad_plan)

    assert not root.exists()


def test_publish_same_plan_twice_is_exact_byte_idempotent(tmp_path: Path) -> None:
    plan = sample_plan()
    root = tmp_path / "snapshots"

    first = publish_local_daily_market_data_snapshot(snapshot_root=root, plan=plan)
    hashes_before = _bundle_hashes(first.path)
    second = publish_local_daily_market_data_snapshot(snapshot_root=root, plan=plan)

    assert first.status is LocalDailyMarketDataSnapshotPublicationStatus.CREATED
    assert (
        second.status is LocalDailyMarketDataSnapshotPublicationStatus.ALREADY_PRESENT
    )
    assert second.path == first.path
    assert _bundle_hashes(first.path) == hashes_before
    assert {path.name for path in (root / "daily-market-data").iterdir()} == {
        ".staging",
        plan.snapshot_id,
    }
    assert second.verified.snapshot_id == plan.snapshot_id


@pytest.mark.parametrize("relative_path", EXPECTED_BUNDLE_FILES)
def test_existing_authoritative_file_mutation_is_conflict(
    tmp_path: Path,
    relative_path: str,
) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_snapshot(
        snapshot_root=tmp_path,
        plan=plan,
    )
    target = result.path / relative_path
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(DailyMarketDataSnapshotConflictError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert target.read_bytes().endswith(b" ")


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_missing_or_extra_file_fails_republish_and_read_only_verifier(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_snapshot(
        snapshot_root=tmp_path,
        plan=plan,
    )
    if mutation == "missing":
        (result.path / "policy.json").unlink()
    else:
        (result.path / "extra.json").write_bytes(b"{}\n")

    with pytest.raises(DailyMarketDataSnapshotDiskVerificationError):
        verify_local_daily_market_data_snapshot(
            snapshot_root=tmp_path,
            snapshot_id=plan.snapshot_id,
        )
    with pytest.raises(DailyMarketDataSnapshotConflictError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)


def test_path_type_failures_are_closed(tmp_path: Path) -> None:
    plan = sample_plan()
    root_file = tmp_path / "root-file"
    root_file.write_text("not a directory")
    with pytest.raises(DailyMarketDataSnapshotPathError):
        publish_local_daily_market_data_snapshot(snapshot_root=root_file, plan=plan)
    with pytest.raises(DailyMarketDataSnapshotPathError):
        verify_local_daily_market_data_snapshot(
            snapshot_root=root_file,
            snapshot_id=plan.snapshot_id,
        )

    root = tmp_path / "root"
    root.mkdir()
    (root / "daily-market-data").write_text("not a directory")
    with pytest.raises(DailyMarketDataSnapshotPathError):
        publish_local_daily_market_data_snapshot(snapshot_root=root, plan=plan)

    root2 = tmp_path / "root2"
    data_root = root2 / "daily-market-data"
    data_root.mkdir(parents=True)
    (data_root / ".staging").write_text("not a directory")
    with pytest.raises(DailyMarketDataSnapshotPathError):
        publish_local_daily_market_data_snapshot(snapshot_root=root2, plan=plan)


def test_symlinked_managed_paths_fail_closed(tmp_path: Path) -> None:
    _require_symlink_support(tmp_path)
    plan = sample_plan()

    actual_root = tmp_path / "actual-root"
    actual_root.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(actual_root, target_is_directory=True)
    with pytest.raises(DailyMarketDataSnapshotPathError):
        publish_local_daily_market_data_snapshot(snapshot_root=root_link, plan=plan)

    root = tmp_path / "root"
    root.mkdir()
    daily_target = tmp_path / "daily-target"
    daily_target.mkdir()
    (root / "daily-market-data").symlink_to(daily_target, target_is_directory=True)
    with pytest.raises(DailyMarketDataSnapshotPathError):
        publish_local_daily_market_data_snapshot(snapshot_root=root, plan=plan)

    root2 = tmp_path / "root2"
    data_root = root2 / "daily-market-data"
    data_root.mkdir(parents=True)
    staging_target = tmp_path / "staging-target"
    staging_target.mkdir()
    (data_root / ".staging").symlink_to(staging_target, target_is_directory=True)
    with pytest.raises(DailyMarketDataSnapshotPathError):
        publish_local_daily_market_data_snapshot(snapshot_root=root2, plan=plan)

    root3 = tmp_path / "root3"
    data_root3 = root3 / "daily-market-data"
    data_root3.mkdir(parents=True)
    final_target = tmp_path / "final-target"
    final_target.mkdir()
    (data_root3 / plan.snapshot_id).symlink_to(final_target, target_is_directory=True)
    with pytest.raises(DailyMarketDataSnapshotConflictError):
        publish_local_daily_market_data_snapshot(snapshot_root=root3, plan=plan)

    result = publish_local_daily_market_data_snapshot(
        snapshot_root=tmp_path / "root4",
        plan=plan,
    )
    (result.path / "bars.jsonl").unlink()
    (result.path / "bars.jsonl").symlink_to(tmp_path / "linked-bars.jsonl")
    with pytest.raises(DailyMarketDataSnapshotPathError):
        verify_local_daily_market_data_snapshot(
            snapshot_root=tmp_path / "root4",
            snapshot_id=plan.snapshot_id,
        )
    with pytest.raises(DailyMarketDataSnapshotConflictError):
        publish_local_daily_market_data_snapshot(
            snapshot_root=tmp_path / "root4",
            plan=plan,
        )


@pytest.mark.parametrize(
    "snapshot_id",
    [
        "../../escape",
        "/absolute/path",
        "foo/bar",
        r"foo\bar",
        ".",
        "..",
        "daily-market-data-snapshot-v1-not-a-hash",
        "daily-market-data-snapshot-v1-" + "A" * 64,
    ],
)
def test_local_verifier_rejects_snapshot_id_traversal(
    tmp_path: Path,
    snapshot_id: str,
) -> None:
    tmp_path.mkdir(exist_ok=True)

    with pytest.raises(DailyMarketDataSnapshotPathError):
        verify_local_daily_market_data_snapshot(
            snapshot_root=tmp_path,
            snapshot_id=snapshot_id,
        )


def test_staging_write_failure_cleans_only_invocation_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()
    root = tmp_path / "snapshots"
    staging_root = root / "daily-market-data" / ".staging"
    unrelated = staging_root / "unrelated"
    unrelated.mkdir(parents=True)

    def fail_mid_write(
        *,
        staging_path: Path,
        planned_files: dict[str, bytes],
    ) -> None:
        (staging_path / "bars.jsonl").write_bytes(planned_files["bars.jsonl"])
        raise DailyMarketDataSnapshotPublicationError("simulated write failure")

    monkeypatch.setattr(local_storage, "_write_planned_files", fail_mid_write)

    with pytest.raises(DailyMarketDataSnapshotPublicationError):
        publish_local_daily_market_data_snapshot(snapshot_root=root, plan=plan)

    assert not (root / "daily-market-data" / plan.snapshot_id).exists()
    assert unrelated.exists()
    assert list(staging_root.iterdir()) == [unrelated]


def test_staging_verification_failure_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_staging_verification(**_: object) -> None:
        raise DailyMarketDataSnapshotPublicationError("simulated staging verification")

    monkeypatch.setattr(
        local_storage,
        "_verify_staged_or_final_bytes",
        fail_staging_verification,
    )

    with pytest.raises(DailyMarketDataSnapshotPublicationError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert not (tmp_path / "daily-market-data" / plan.snapshot_id).exists()
    assert list((tmp_path / "daily-market-data" / ".staging").iterdir()) == []


def test_same_id_rename_race_returns_already_present_for_exact_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def race_with_identical_final(source: Path, destination: Path) -> None:
        destination.mkdir()
        _write_bundle(destination, plan.as_file_map())
        raise OSError(errno.ENOTEMPTY, "destination exists")

    monkeypatch.setattr(local_storage, "_rename_directory", race_with_identical_final)

    result = publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert (
        result.status is LocalDailyMarketDataSnapshotPublicationStatus.ALREADY_PRESENT
    )
    assert _read_bundle(result.path) == plan.as_file_map()
    assert list((tmp_path / "daily-market-data" / ".staging").iterdir()) == []


def test_same_id_rename_race_with_conflicting_bundle_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def race_with_conflicting_final(source: Path, destination: Path) -> None:
        files = plan.as_file_map()
        files["bars.jsonl"] = files["bars.jsonl"] + b" "
        destination.mkdir()
        _write_bundle(destination, files)
        raise OSError(errno.ENOTEMPTY, "destination exists")

    monkeypatch.setattr(local_storage, "_rename_directory", race_with_conflicting_final)

    with pytest.raises(DailyMarketDataSnapshotConflictError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert list((tmp_path / "daily-market-data" / ".staging").iterdir()) == []


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

    with pytest.raises(DailyMarketDataSnapshotPublicationError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert not (tmp_path / "daily-market-data" / plan.snapshot_id).exists()
    assert list((tmp_path / "daily-market-data" / ".staging").iterdir()) == []


def test_post_rename_verification_failure_leaves_final_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_final_verification(**_: object) -> object:
        raise DailyMarketDataSnapshotDiskVerificationError("simulated final failure")

    monkeypatch.setattr(
        local_storage,
        "verify_local_daily_market_data_snapshot",
        fail_final_verification,
    )

    with pytest.raises(DailyMarketDataSnapshotDiskVerificationError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert (tmp_path / "daily-market-data" / plan.snapshot_id).is_dir()


def test_local_verifier_is_read_only(tmp_path: Path) -> None:
    plan = sample_plan()
    result = publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)
    hashes_before = _bundle_hashes(result.path)

    verified = verify_local_daily_market_data_snapshot(
        snapshot_root=tmp_path,
        snapshot_id=plan.snapshot_id,
    )

    assert verified.snapshot_id == plan.snapshot_id
    assert _bundle_hashes(result.path) == hashes_before


def test_published_snapshot_relocates_under_new_root(tmp_path: Path) -> None:
    plan = sample_plan()
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    result = publish_local_daily_market_data_snapshot(snapshot_root=root_a, plan=plan)
    target = root_b / "daily-market-data" / plan.snapshot_id
    target.parent.mkdir(parents=True)
    shutil.copytree(result.path, target)

    verified = verify_local_daily_market_data_snapshot(
        snapshot_root=root_b,
        snapshot_id=plan.snapshot_id,
    )

    assert verified.snapshot_id == plan.snapshot_id
    assert (target / "snapshot-manifest.json").read_bytes() == (
        result.path / "snapshot-manifest.json"
    ).read_bytes()
    for content in _read_bundle(target).values():
        assert str(root_a).encode() not in content
        assert str(root_b).encode() not in content


def test_staging_namespace_is_not_authoritative_and_unrelated_child_remains(
    tmp_path: Path,
) -> None:
    plan = sample_plan()
    staging_root = tmp_path / "daily-market-data" / ".staging"
    unrelated = staging_root / "manual-orphan"
    unrelated.mkdir(parents=True)

    result = publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert result.status is LocalDailyMarketDataSnapshotPublicationStatus.CREATED
    assert unrelated.exists()
    assert (
        verify_local_daily_market_data_snapshot(
            snapshot_root=tmp_path,
            snapshot_id=plan.snapshot_id,
        ).snapshot_id
        == plan.snapshot_id
    )


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

    publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert fsync_calls == len(EXPECTED_BUNDLE_FILES)
    assert directory_fsyncs == [
        tmp_path.resolve()
        / "daily-market-data"
        / ".staging"
        / directory_fsyncs[0].name,
        tmp_path.resolve() / "daily-market-data",
    ]


def test_unsupported_directory_fsync_errno_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_open(path: Path, flags: int) -> int:
        raise OSError(errno.EINVAL, "directory fsync unsupported")

    monkeypatch.setattr(local_storage.os, "open", unsupported_open)

    local_storage._fsync_directory(tmp_path)


def test_directory_fsync_error_fails_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = sample_plan()

    def fail_directory_fsync(directory: Path) -> None:
        raise OSError(errno.EIO, "simulated directory fsync failure")

    monkeypatch.setattr(local_storage, "_fsync_directory", fail_directory_fsync)

    with pytest.raises(DailyMarketDataSnapshotPublicationError):
        publish_local_daily_market_data_snapshot(snapshot_root=tmp_path, plan=plan)

    assert not (tmp_path / "daily-market-data" / plan.snapshot_id).exists()


def _read_bundle(directory: Path) -> dict[str, bytes]:
    return {
        relative_path: (directory / relative_path).read_bytes()
        for relative_path in EXPECTED_BUNDLE_FILES
    }


def _write_bundle(directory: Path, files: dict[str, bytes]) -> None:
    for relative_path in EXPECTED_BUNDLE_FILES:
        (directory / relative_path).write_bytes(files[relative_path])


def _bundle_hashes(directory: Path) -> dict[str, str]:
    return {
        relative_path: sha256((directory / relative_path).read_bytes()).hexdigest()
        for relative_path in EXPECTED_BUNDLE_FILES
    }


def _require_symlink_support(tmp_path: Path) -> None:
    target = tmp_path / "symlink-target"
    link = tmp_path / "symlink-link"
    target.write_text("target")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is not supported: {exc}")
