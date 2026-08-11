"""Local filesystem publication for immutable daily market-data snapshots."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from research_sdk.contracts.daily_market_data_snapshots import (
    DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,
    REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES,
    SNAPSHOT_ID_PATTERN,
)
from research_sdk.daily_market_data_storage.planning import (
    DailyMarketDataSnapshotPlan,
)
from research_sdk.daily_market_data_storage.verification import (
    VerifiedDailyMarketDataSnapshot,
    verify_daily_market_data_snapshot_bundle,
)

_DAILY_MARKET_DATA_DIR = "daily-market-data"
_STAGING_DIR = ".staging"
_EXPECTED_BUNDLE_PATHS = tuple(
    path for _, path, _ in REQUIRED_DAILY_MARKET_DATA_SNAPSHOT_FILES
) + (DAILY_MARKET_DATA_BUNDLE_MANIFEST_PATH,)
_DESTINATION_EXISTS_ERRNOS = {errno.EEXIST, errno.ENOTEMPTY}
_UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS = {
    errno.EINVAL,
    getattr(errno, "ENOTSUP", None),
    getattr(errno, "EOPNOTSUPP", None),
} - {None}


class LocalDailyMarketDataSnapshotPublicationStatus(StrEnum):
    """Operational status for local snapshot publication."""

    CREATED = "CREATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class LocalDailyMarketDataSnapshotPublication:
    """Operational result for local daily market-data snapshot publication."""

    snapshot_id: str
    path: Path
    status: LocalDailyMarketDataSnapshotPublicationStatus
    verified: VerifiedDailyMarketDataSnapshot


class DailyMarketDataSnapshotStorageError(Exception):
    """Base error for local daily market-data snapshot storage failures."""


class DailyMarketDataSnapshotPathError(DailyMarketDataSnapshotStorageError):
    """Raised when a local snapshot storage path is unsafe or malformed."""


class DailyMarketDataSnapshotPublicationError(DailyMarketDataSnapshotStorageError):
    """Raised when local snapshot publication cannot complete."""


class DailyMarketDataSnapshotConflictError(DailyMarketDataSnapshotStorageError):
    """Raised when an existing immutable snapshot conflicts with a publish plan."""


class DailyMarketDataSnapshotDiskVerificationError(DailyMarketDataSnapshotStorageError):
    """Raised when expected on-disk snapshot bytes fail verification."""


def publish_local_daily_market_data_snapshot(
    *,
    snapshot_root: Path,
    plan: DailyMarketDataSnapshotPlan,
) -> LocalDailyMarketDataSnapshotPublication:
    """Publish exact planned S3b1 snapshot bytes under a local snapshot root."""

    planned_files, _ = _validate_plan_before_io(plan)
    root = _prepare_snapshot_root_for_publication(snapshot_root)
    data_root = _prepare_managed_data_root(root)
    final_path = _snapshot_directory(data_root=data_root, snapshot_id=plan.snapshot_id)

    if final_path.exists() or final_path.is_symlink():
        return _idempotent_publication_or_conflict(
            root=root,
            final_path=final_path,
            snapshot_id=plan.snapshot_id,
            planned_files=planned_files,
        )

    staging_root = _prepare_staging_root(data_root)
    staging_path: Path | None = None
    rename_succeeded = False
    try:
        staging_path = _create_staging_directory(
            staging_root=staging_root,
            snapshot_id=plan.snapshot_id,
        )
        _write_planned_files(staging_path=staging_path, planned_files=planned_files)
        _fsync_directory(staging_path)
        _verify_staged_or_final_bytes(
            directory=staging_path,
            snapshot_id=plan.snapshot_id,
            planned_files=planned_files,
            error_type=DailyMarketDataSnapshotPublicationError,
            context="staged snapshot verification failed",
        )
        _rename_directory(staging_path, final_path)
        rename_succeeded = True
    except OSError as exc:
        if (
            staging_path is not None
            and not rename_succeeded
            and exc.errno in _DESTINATION_EXISTS_ERRNOS
        ):
            try:
                publication = _idempotent_publication_or_conflict(
                    root=root,
                    final_path=final_path,
                    snapshot_id=plan.snapshot_id,
                    planned_files=planned_files,
                )
            finally:
                _cleanup_staging_best_effort(staging_path)
            return publication
        _cleanup_staging_after_failure(staging_path, exc)
        raise DailyMarketDataSnapshotPublicationError(
            f"failed to publish local daily market-data snapshot "
            f"{plan.snapshot_id!r} to {final_path}"
        ) from exc
    except Exception as exc:
        _cleanup_staging_after_failure(staging_path, exc)
        raise

    try:
        _fsync_directory(data_root)
        verified = verify_local_daily_market_data_snapshot(
            snapshot_root=root,
            snapshot_id=plan.snapshot_id,
        )
        final_files = _read_authoritative_bundle_directory(final_path)
        _require_exact_bytes(
            actual=final_files,
            expected=planned_files,
            error_type=DailyMarketDataSnapshotDiskVerificationError,
            context="published final snapshot bytes differ from plan",
        )
    except Exception as exc:
        raise DailyMarketDataSnapshotDiskVerificationError(
            f"published local daily market-data snapshot {plan.snapshot_id!r} "
            f"failed final verification at {final_path}"
        ) from exc

    return LocalDailyMarketDataSnapshotPublication(
        snapshot_id=plan.snapshot_id,
        path=final_path,
        status=LocalDailyMarketDataSnapshotPublicationStatus.CREATED,
        verified=verified,
    )


def verify_local_daily_market_data_snapshot(
    *,
    snapshot_root: Path,
    snapshot_id: str,
) -> VerifiedDailyMarketDataSnapshot:
    """Read and verify a local daily market-data snapshot without mutation."""

    _validate_snapshot_id(snapshot_id)
    root = _validate_existing_snapshot_root(snapshot_root)
    data_root = _require_existing_directory(
        root / _DAILY_MARKET_DATA_DIR,
        context="daily market-data storage directory",
    )
    final_path = _snapshot_directory(data_root=data_root, snapshot_id=snapshot_id)
    files = _read_authoritative_bundle_directory(final_path)
    try:
        verified = verify_daily_market_data_snapshot_bundle(files)
    except Exception as exc:
        raise DailyMarketDataSnapshotDiskVerificationError(
            f"local daily market-data snapshot {snapshot_id!r} failed "
            f"S3b1 verification at {final_path}"
        ) from exc
    if verified.snapshot_id != snapshot_id:
        raise DailyMarketDataSnapshotDiskVerificationError(
            f"local daily market-data snapshot at {final_path} verified as "
            f"{verified.snapshot_id!r}, not requested {snapshot_id!r}"
        )
    return verified


def _validate_plan_before_io(
    plan: DailyMarketDataSnapshotPlan,
) -> tuple[dict[str, bytes], VerifiedDailyMarketDataSnapshot]:
    try:
        planned_files = plan.as_file_map()
        verified = verify_daily_market_data_snapshot_bundle(planned_files)
    except Exception as exc:
        raise DailyMarketDataSnapshotPublicationError(
            "daily market-data snapshot plan failed pure S3b1 verification "
            "before filesystem access"
        ) from exc
    _validate_snapshot_id(plan.snapshot_id)
    if verified.snapshot_id != plan.snapshot_id:
        raise DailyMarketDataSnapshotPublicationError(
            f"daily market-data snapshot plan ID {plan.snapshot_id!r} does not "
            f"match verified bundle ID {verified.snapshot_id!r}"
        )
    return planned_files, verified


def _validate_snapshot_id(snapshot_id: str) -> None:
    if SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id) is None:
        raise DailyMarketDataSnapshotPathError(
            "snapshot_id must use daily-market-data-snapshot-v1-<64 lowercase hex>"
        )


def _prepare_snapshot_root_for_publication(snapshot_root: Path) -> Path:
    root = Path(snapshot_root).expanduser().absolute()
    if root.exists() or root.is_symlink():
        return _require_existing_directory(root, context="snapshot root")
    try:
        root.mkdir(parents=True)
    except OSError as exc:
        raise DailyMarketDataSnapshotPathError(
            f"failed to create snapshot root {root}"
        ) from exc
    return _require_existing_directory(root, context="snapshot root")


def _validate_existing_snapshot_root(snapshot_root: Path) -> Path:
    root = Path(snapshot_root).expanduser().absolute()
    return _require_existing_directory(root, context="snapshot root")


def _prepare_managed_data_root(root: Path) -> Path:
    data_root = root / _DAILY_MARKET_DATA_DIR
    if data_root.exists() or data_root.is_symlink():
        return _require_existing_directory(
            data_root,
            context="daily market-data storage directory",
        )
    try:
        data_root.mkdir()
    except OSError as exc:
        raise DailyMarketDataSnapshotPathError(
            f"failed to create daily market-data storage directory {data_root}"
        ) from exc
    return _require_existing_directory(
        data_root,
        context="daily market-data storage directory",
    )


def _prepare_staging_root(data_root: Path) -> Path:
    staging_root = data_root / _STAGING_DIR
    if staging_root.exists() or staging_root.is_symlink():
        return _require_existing_directory(staging_root, context="staging directory")
    try:
        staging_root.mkdir()
    except OSError as exc:
        raise DailyMarketDataSnapshotPathError(
            f"failed to create staging directory {staging_root}"
        ) from exc
    return _require_existing_directory(staging_root, context="staging directory")


def _require_existing_directory(path: Path, *, context: str) -> Path:
    if path.is_symlink():
        raise DailyMarketDataSnapshotPathError(
            f"{context} must not be a symlink: {path}"
        )
    try:
        metadata = path.stat()
    except OSError as exc:
        raise DailyMarketDataSnapshotPathError(
            f"{context} is not an accessible directory: {path}"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise DailyMarketDataSnapshotPathError(f"{context} must be a directory: {path}")
    return path.resolve(strict=True)


def _snapshot_directory(*, data_root: Path, snapshot_id: str) -> Path:
    _validate_snapshot_id(snapshot_id)
    final_path = data_root / snapshot_id
    try:
        final_path.absolute().relative_to(data_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DailyMarketDataSnapshotPathError(
            f"snapshot path escapes managed data root: {final_path}"
        ) from exc
    return final_path


def _create_staging_directory(*, staging_root: Path, snapshot_id: str) -> Path:
    _validate_snapshot_id(snapshot_id)
    prefix = f"{snapshot_id}.{os.getpid()}."
    try:
        staging_path = Path(tempfile.mkdtemp(prefix=prefix, dir=staging_root))
    except OSError as exc:
        raise DailyMarketDataSnapshotPublicationError(
            f"failed to create staging directory under {staging_root}"
        ) from exc
    if staging_path.is_symlink():
        raise DailyMarketDataSnapshotPathError(
            f"created staging directory must not be a symlink: {staging_path}"
        )
    return _require_existing_directory(
        staging_path, context="created staging directory"
    )


def _write_planned_files(
    *,
    staging_path: Path,
    planned_files: Mapping[str, bytes],
) -> None:
    for relative_path in _EXPECTED_BUNDLE_PATHS:
        file_path = staging_path / relative_path
        if file_path.exists() or file_path.is_symlink():
            raise DailyMarketDataSnapshotPublicationError(
                f"staging file already exists before exclusive write: {file_path}"
            )
        try:
            with file_path.open("xb") as file:
                file.write(planned_files[relative_path])
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            raise DailyMarketDataSnapshotPublicationError(
                f"failed to write and fsync staged snapshot file {file_path}"
            ) from exc


def _read_authoritative_bundle_directory(directory: Path) -> dict[str, bytes]:
    directory = _require_existing_directory(
        directory,
        context="authoritative snapshot directory",
    )
    try:
        entry_names = {entry.name for entry in directory.iterdir()}
    except OSError as exc:
        raise DailyMarketDataSnapshotPathError(
            f"failed to enumerate authoritative snapshot directory {directory}"
        ) from exc
    expected = set(_EXPECTED_BUNDLE_PATHS)
    if entry_names != expected:
        missing = sorted(expected - entry_names)
        unexpected = sorted(entry_names - expected)
        raise DailyMarketDataSnapshotDiskVerificationError(
            f"bundle file set mismatch at {directory}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    files: dict[str, bytes] = {}
    for relative_path in _EXPECTED_BUNDLE_PATHS:
        file_path = directory / relative_path
        files[relative_path] = _read_authoritative_file(file_path)
    return files


def _read_authoritative_file(file_path: Path) -> bytes:
    if file_path.is_symlink():
        raise DailyMarketDataSnapshotPathError(
            f"authoritative snapshot file must not be a symlink: {file_path}"
        )
    try:
        metadata = file_path.lstat()
    except OSError as exc:
        raise DailyMarketDataSnapshotPathError(
            f"authoritative snapshot file is not accessible: {file_path}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise DailyMarketDataSnapshotPathError(
            f"authoritative snapshot file must be a regular file: {file_path}"
        )
    try:
        return file_path.read_bytes()
    except OSError as exc:
        raise DailyMarketDataSnapshotDiskVerificationError(
            f"failed to read authoritative snapshot file {file_path}"
        ) from exc


def _verify_staged_or_final_bytes(
    *,
    directory: Path,
    snapshot_id: str,
    planned_files: Mapping[str, bytes],
    error_type: type[DailyMarketDataSnapshotStorageError],
    context: str,
) -> VerifiedDailyMarketDataSnapshot:
    try:
        files = _read_authoritative_bundle_directory(directory)
        verified = verify_daily_market_data_snapshot_bundle(files)
        if verified.snapshot_id != snapshot_id:
            raise DailyMarketDataSnapshotDiskVerificationError(
                f"verified snapshot ID {verified.snapshot_id!r} does not match "
                f"requested {snapshot_id!r}"
            )
        _require_exact_bytes(
            actual=files,
            expected=planned_files,
            error_type=error_type,
            context=f"{context}: staged bytes differ from plan",
        )
    except DailyMarketDataSnapshotStorageError as exc:
        if isinstance(exc, error_type):
            raise
        raise error_type(f"{context} at {directory}") from exc
    except Exception as exc:
        raise error_type(f"{context} at {directory}") from exc
    return verified


def _require_exact_bytes(
    *,
    actual: Mapping[str, bytes],
    expected: Mapping[str, bytes],
    error_type: type[DailyMarketDataSnapshotStorageError],
    context: str,
) -> None:
    if set(actual) != set(expected):
        raise error_type(f"{context}: file sets differ")
    for relative_path in _EXPECTED_BUNDLE_PATHS:
        if actual[relative_path] != expected[relative_path]:
            raise error_type(f"{context}: {relative_path} differs")


def _idempotent_publication_or_conflict(
    *,
    root: Path,
    final_path: Path,
    snapshot_id: str,
    planned_files: Mapping[str, bytes],
) -> LocalDailyMarketDataSnapshotPublication:
    try:
        verified = verify_local_daily_market_data_snapshot(
            snapshot_root=root,
            snapshot_id=snapshot_id,
        )
        actual_files = _read_authoritative_bundle_directory(final_path)
        _require_exact_bytes(
            actual=actual_files,
            expected=planned_files,
            error_type=DailyMarketDataSnapshotConflictError,
            context="existing local snapshot conflicts with requested plan",
        )
    except DailyMarketDataSnapshotConflictError:
        raise
    except Exception as exc:
        raise DailyMarketDataSnapshotConflictError(
            f"existing local daily market-data snapshot at {final_path} "
            f"does not exactly match requested immutable plan {snapshot_id!r}"
        ) from exc
    return LocalDailyMarketDataSnapshotPublication(
        snapshot_id=snapshot_id,
        path=final_path,
        status=LocalDailyMarketDataSnapshotPublicationStatus.ALREADY_PRESENT,
        verified=verified,
    )


def _rename_directory(source: Path, destination: Path) -> None:
    os.rename(source, destination)


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
                return
            raise
    finally:
        os.close(descriptor)


def _cleanup_staging_after_failure(
    staging_path: Path | None,
    original_exception: BaseException,
) -> None:
    if staging_path is None:
        return
    try:
        _cleanup_staging_best_effort(staging_path)
    except Exception as cleanup_exc:
        original_exception.add_note(
            f"failed to clean staging directory {staging_path}: {cleanup_exc}"
        )


def _cleanup_staging_best_effort(staging_path: Path) -> None:
    if staging_path.exists() or staging_path.is_symlink():
        shutil.rmtree(staging_path)


__all__ = [
    "DailyMarketDataSnapshotConflictError",
    "DailyMarketDataSnapshotDiskVerificationError",
    "DailyMarketDataSnapshotPathError",
    "DailyMarketDataSnapshotPublicationError",
    "DailyMarketDataSnapshotStorageError",
    "LocalDailyMarketDataSnapshotPublication",
    "LocalDailyMarketDataSnapshotPublicationStatus",
    "publish_local_daily_market_data_snapshot",
    "verify_local_daily_market_data_snapshot",
]
