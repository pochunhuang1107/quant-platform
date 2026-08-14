"""Local filesystem publication for immutable source captures."""

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
from types import MappingProxyType

from research_sdk.daily_market_data_source_capture.models import (
    SOURCE_CAPTURE_ID_PATTERN,
    SOURCE_CAPTURE_REQUIRED_PATHS,
)
from research_sdk.daily_market_data_source_capture.planning import (
    PlannedDailyMarketDataSourceCapture,
)
from research_sdk.daily_market_data_source_capture.verification import (
    VerifiedDailyMarketDataSourceCapture,
    verify_daily_market_data_source_capture,
)

_SOURCE_CAPTURE_DIR = "daily-market-data-source-captures"
_STAGING_DIR = ".staging"
_DESTINATION_EXISTS_ERRNOS = {errno.EEXIST, errno.ENOTEMPTY}
_UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS = {
    errno.EINVAL,
    getattr(errno, "ENOTSUP", None),
    getattr(errno, "EOPNOTSUPP", None),
} - {None}


class LocalDailyMarketDataSourceCapturePublicationStatus(StrEnum):
    """Operational status for local source-capture publication."""

    CREATED = "CREATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class LocalDailyMarketDataSourceCapturePublication:
    """Operational result for local source-capture publication."""

    capture_id: str
    path: Path
    status: LocalDailyMarketDataSourceCapturePublicationStatus
    verified: VerifiedDailyMarketDataSourceCapture


class DailyMarketDataSourceCaptureStorageError(Exception):
    """Base error for local source-capture storage failures."""


class DailyMarketDataSourceCapturePathError(DailyMarketDataSourceCaptureStorageError):
    """Raised when a local source-capture storage path is unsafe or malformed."""


class DailyMarketDataSourceCapturePublicationError(
    DailyMarketDataSourceCaptureStorageError
):
    """Raised when local source-capture publication cannot complete."""


class DailyMarketDataSourceCaptureConflictError(
    DailyMarketDataSourceCaptureStorageError
):
    """Raised when an existing immutable source capture conflicts with a plan."""


class DailyMarketDataSourceCaptureDiskVerificationError(
    DailyMarketDataSourceCaptureStorageError
):
    """Raised when expected on-disk source-capture bytes fail verification."""


@dataclass(frozen=True)
class _LoadedLocalSourceCapture:
    path: Path
    files: Mapping[str, bytes]
    verified: VerifiedDailyMarketDataSourceCapture


def publish_local_daily_market_data_source_capture(
    *,
    source_capture_root: Path,
    plan: PlannedDailyMarketDataSourceCapture,
) -> LocalDailyMarketDataSourceCapturePublication:
    """Publish exact planned source-capture bytes under a local storage root."""

    planned_files, _ = _validate_plan_before_io(plan)
    root = _prepare_source_capture_root_for_publication(source_capture_root)
    data_root = _prepare_managed_data_root(root)
    final_path = _source_capture_directory(
        data_root=data_root,
        capture_id=plan.capture_id,
    )

    if final_path.exists() or final_path.is_symlink():
        return _idempotent_publication_or_conflict(
            root=root,
            final_path=final_path,
            capture_id=plan.capture_id,
            planned_files=planned_files,
        )

    staging_root = _prepare_staging_root(data_root)
    staging_path: Path | None = None
    rename_succeeded = False
    try:
        staging_path = _create_staging_directory(
            staging_root=staging_root,
            capture_id=plan.capture_id,
        )
        _write_planned_files(staging_path=staging_path, planned_files=planned_files)
        _fsync_directory(staging_path)
        _verify_staged_or_final_bytes(
            directory=staging_path,
            capture_id=plan.capture_id,
            planned_files=planned_files,
            error_type=DailyMarketDataSourceCapturePublicationError,
            context="staged source-capture verification failed",
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
                    capture_id=plan.capture_id,
                    planned_files=planned_files,
                )
            except Exception as race_exc:
                _cleanup_staging_after_failure(staging_path, race_exc)
                raise
            try:
                _cleanup_staging_best_effort(staging_path)
            except Exception as cleanup_exc:
                raise DailyMarketDataSourceCapturePublicationError(
                    f"failed to clean staging directory {staging_path} after "
                    "destination race"
                ) from cleanup_exc
            return publication
        _cleanup_staging_after_failure(staging_path, exc)
        raise DailyMarketDataSourceCapturePublicationError(
            f"failed to publish local source capture {plan.capture_id!r} "
            f"to {final_path}"
        ) from exc
    except Exception as exc:
        if not rename_succeeded:
            _cleanup_staging_after_failure(staging_path, exc)
        raise

    try:
        _fsync_directory(data_root)
        loaded = _load_local_source_capture_files_and_verify(
            source_capture_root=root,
            capture_id=plan.capture_id,
        )
        _require_exact_bytes(
            actual=loaded.files,
            expected=planned_files,
            error_type=DailyMarketDataSourceCaptureDiskVerificationError,
            context="published final source-capture bytes differ from plan",
        )
    except Exception as exc:
        raise DailyMarketDataSourceCaptureDiskVerificationError(
            f"published local source capture {plan.capture_id!r} failed final "
            f"verification at {final_path}"
        ) from exc

    return LocalDailyMarketDataSourceCapturePublication(
        capture_id=plan.capture_id,
        path=loaded.path,
        status=LocalDailyMarketDataSourceCapturePublicationStatus.CREATED,
        verified=loaded.verified,
    )


def load_local_daily_market_data_source_capture(
    *,
    source_capture_root: Path,
    capture_id: str,
) -> VerifiedDailyMarketDataSourceCapture:
    """Read and verify a local source capture without filesystem mutation."""

    return _load_local_source_capture_files_and_verify(
        source_capture_root=source_capture_root,
        capture_id=capture_id,
    ).verified


def _validate_plan_before_io(
    plan: PlannedDailyMarketDataSourceCapture,
) -> tuple[dict[str, bytes], VerifiedDailyMarketDataSourceCapture]:
    try:
        planned_files = plan.as_file_map()
        verified = verify_daily_market_data_source_capture(planned_files)
    except Exception as exc:
        raise DailyMarketDataSourceCapturePublicationError(
            "source-capture plan failed pure S3c3b1 verification before "
            "filesystem access"
        ) from exc
    _validate_capture_id(plan.capture_id)
    if verified.capture_id != plan.capture_id:
        raise DailyMarketDataSourceCapturePublicationError(
            f"source-capture plan ID {plan.capture_id!r} does not match "
            f"verified capture ID {verified.capture_id!r}"
        )
    return planned_files, verified


def _load_local_source_capture_files_and_verify(
    *,
    source_capture_root: Path,
    capture_id: str,
) -> _LoadedLocalSourceCapture:
    _validate_capture_id(capture_id)
    root = _validate_existing_source_capture_root(source_capture_root)
    data_root = _require_existing_directory(
        root / _SOURCE_CAPTURE_DIR,
        context="source-capture storage directory",
    )
    final_path = _source_capture_directory(data_root=data_root, capture_id=capture_id)
    files = _read_authoritative_source_capture_directory(final_path)
    try:
        verified = verify_daily_market_data_source_capture(files)
    except Exception as exc:
        raise DailyMarketDataSourceCaptureDiskVerificationError(
            f"local source capture {capture_id!r} failed S3c3b1 verification "
            f"at {final_path}"
        ) from exc
    if verified.capture_id != capture_id:
        raise DailyMarketDataSourceCaptureDiskVerificationError(
            f"local source capture at {final_path} verified as "
            f"{verified.capture_id!r}, not requested {capture_id!r}"
        )
    return _LoadedLocalSourceCapture(
        path=final_path.resolve(strict=True),
        files=MappingProxyType(dict(files)),
        verified=verified,
    )


def _validate_capture_id(capture_id: str) -> None:
    if SOURCE_CAPTURE_ID_PATTERN.fullmatch(capture_id) is None:
        raise DailyMarketDataSourceCapturePathError(
            "capture_id must use daily-market-data-source-capture-v1-<64 lowercase hex>"
        )


def _prepare_source_capture_root_for_publication(source_capture_root: Path) -> Path:
    root = Path(source_capture_root).expanduser().absolute()
    if root.exists() or root.is_symlink():
        return _require_existing_directory(root, context="source-capture root")
    try:
        root.mkdir(parents=True)
    except OSError as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"failed to create source-capture root {root}"
        ) from exc
    return _require_existing_directory(root, context="source-capture root")


def _validate_existing_source_capture_root(source_capture_root: Path) -> Path:
    root = Path(source_capture_root).expanduser().absolute()
    return _require_existing_directory(root, context="source-capture root")


def _prepare_managed_data_root(root: Path) -> Path:
    data_root = root / _SOURCE_CAPTURE_DIR
    if data_root.exists() or data_root.is_symlink():
        return _require_existing_directory(
            data_root,
            context="source-capture storage directory",
        )
    try:
        data_root.mkdir()
    except OSError as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"failed to create source-capture storage directory {data_root}"
        ) from exc
    return _require_existing_directory(
        data_root,
        context="source-capture storage directory",
    )


def _prepare_staging_root(data_root: Path) -> Path:
    staging_root = data_root / _STAGING_DIR
    if staging_root.exists() or staging_root.is_symlink():
        return _require_existing_directory(staging_root, context="staging directory")
    try:
        staging_root.mkdir()
    except OSError as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"failed to create staging directory {staging_root}"
        ) from exc
    return _require_existing_directory(staging_root, context="staging directory")


def _require_existing_directory(path: Path, *, context: str) -> Path:
    if path.is_symlink():
        raise DailyMarketDataSourceCapturePathError(
            f"{context} must not be a symlink: {path}"
        )
    try:
        metadata = path.stat()
    except OSError as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"{context} is not an accessible directory: {path}"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise DailyMarketDataSourceCapturePathError(
            f"{context} must be a directory: {path}"
        )
    return path.resolve(strict=True)


def _source_capture_directory(*, data_root: Path, capture_id: str) -> Path:
    _validate_capture_id(capture_id)
    final_path = data_root / capture_id
    try:
        final_path.absolute().relative_to(data_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"source-capture path escapes managed data root: {final_path}"
        ) from exc
    return final_path


def _create_staging_directory(*, staging_root: Path, capture_id: str) -> Path:
    _validate_capture_id(capture_id)
    prefix = f"{capture_id}.{os.getpid()}."
    try:
        staging_path = Path(tempfile.mkdtemp(prefix=prefix, dir=staging_root))
    except OSError as exc:
        raise DailyMarketDataSourceCapturePublicationError(
            f"failed to create staging directory under {staging_root}"
        ) from exc
    if staging_path.is_symlink():
        raise DailyMarketDataSourceCapturePathError(
            f"created staging directory must not be a symlink: {staging_path}"
        )
    staging_path = _require_existing_directory(
        staging_path,
        context="created staging directory",
    )
    try:
        staging_path.relative_to(staging_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"created staging directory escapes staging root: {staging_path}"
        ) from exc
    return staging_path


def _write_planned_files(
    *,
    staging_path: Path,
    planned_files: Mapping[str, bytes],
) -> None:
    for relative_path in SOURCE_CAPTURE_REQUIRED_PATHS:
        file_path = staging_path / relative_path
        if file_path.exists() or file_path.is_symlink():
            raise DailyMarketDataSourceCapturePublicationError(
                f"staging file already exists before exclusive write: {file_path}"
            )
        try:
            with file_path.open("xb") as file:
                file.write(planned_files[relative_path])
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            raise DailyMarketDataSourceCapturePublicationError(
                f"failed to write and fsync staged source-capture file {file_path}"
            ) from exc


def _read_authoritative_source_capture_directory(directory: Path) -> dict[str, bytes]:
    directory = _require_existing_directory(
        directory,
        context="authoritative source-capture directory",
    )
    try:
        entry_names = {entry.name for entry in directory.iterdir()}
    except OSError as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"failed to enumerate authoritative source-capture directory {directory}"
        ) from exc
    expected = set(SOURCE_CAPTURE_REQUIRED_PATHS)
    if entry_names != expected:
        missing = sorted(expected - entry_names)
        unexpected = sorted(entry_names - expected)
        raise DailyMarketDataSourceCaptureDiskVerificationError(
            f"source-capture file set mismatch at {directory}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    files: dict[str, bytes] = {}
    for relative_path in SOURCE_CAPTURE_REQUIRED_PATHS:
        file_path = directory / relative_path
        files[relative_path] = _read_authoritative_file(file_path)
    return files


def _read_authoritative_file(file_path: Path) -> bytes:
    if file_path.is_symlink():
        raise DailyMarketDataSourceCapturePathError(
            f"authoritative source-capture file must not be a symlink: {file_path}"
        )
    try:
        metadata = file_path.lstat()
    except OSError as exc:
        raise DailyMarketDataSourceCapturePathError(
            f"authoritative source-capture file is not accessible: {file_path}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise DailyMarketDataSourceCapturePathError(
            f"authoritative source-capture file must be a regular file: {file_path}"
        )
    try:
        return file_path.read_bytes()
    except OSError as exc:
        raise DailyMarketDataSourceCaptureDiskVerificationError(
            f"failed to read authoritative source-capture file {file_path}"
        ) from exc


def _verify_staged_or_final_bytes(
    *,
    directory: Path,
    capture_id: str,
    planned_files: Mapping[str, bytes],
    error_type: type[DailyMarketDataSourceCaptureStorageError],
    context: str,
) -> _LoadedLocalSourceCapture:
    try:
        files = _read_authoritative_source_capture_directory(directory)
        verified = verify_daily_market_data_source_capture(files)
        if verified.capture_id != capture_id:
            raise DailyMarketDataSourceCaptureDiskVerificationError(
                f"verified capture ID {verified.capture_id!r} does not match "
                f"requested {capture_id!r}"
            )
        _require_exact_bytes(
            actual=files,
            expected=planned_files,
            error_type=error_type,
            context=f"{context}: staged bytes differ from plan",
        )
    except DailyMarketDataSourceCaptureStorageError as exc:
        if isinstance(exc, error_type):
            raise
        raise error_type(f"{context} at {directory}") from exc
    except Exception as exc:
        raise error_type(f"{context} at {directory}") from exc
    return _LoadedLocalSourceCapture(
        path=directory.resolve(strict=True),
        files=MappingProxyType(dict(files)),
        verified=verified,
    )


def _require_exact_bytes(
    *,
    actual: Mapping[str, bytes],
    expected: Mapping[str, bytes],
    error_type: type[DailyMarketDataSourceCaptureStorageError],
    context: str,
) -> None:
    if set(actual) != set(expected):
        raise error_type(f"{context}: file sets differ")
    for relative_path in SOURCE_CAPTURE_REQUIRED_PATHS:
        if actual[relative_path] != expected[relative_path]:
            raise error_type(f"{context}: {relative_path} differs")


def _idempotent_publication_or_conflict(
    *,
    root: Path,
    final_path: Path,
    capture_id: str,
    planned_files: Mapping[str, bytes],
) -> LocalDailyMarketDataSourceCapturePublication:
    try:
        loaded = _load_local_source_capture_files_and_verify(
            source_capture_root=root,
            capture_id=capture_id,
        )
        _require_exact_bytes(
            actual=loaded.files,
            expected=planned_files,
            error_type=DailyMarketDataSourceCaptureConflictError,
            context="existing local source capture conflicts with requested plan",
        )
    except DailyMarketDataSourceCaptureConflictError:
        raise
    except Exception as exc:
        raise DailyMarketDataSourceCaptureConflictError(
            f"existing local source capture at {final_path} does not exactly "
            f"match requested immutable plan {capture_id!r}"
        ) from exc
    return LocalDailyMarketDataSourceCapturePublication(
        capture_id=capture_id,
        path=loaded.path,
        status=LocalDailyMarketDataSourceCapturePublicationStatus.ALREADY_PRESENT,
        verified=loaded.verified,
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
    "DailyMarketDataSourceCaptureConflictError",
    "DailyMarketDataSourceCaptureDiskVerificationError",
    "DailyMarketDataSourceCapturePathError",
    "DailyMarketDataSourceCapturePublicationError",
    "DailyMarketDataSourceCaptureStorageError",
    "LocalDailyMarketDataSourceCapturePublication",
    "LocalDailyMarketDataSourceCapturePublicationStatus",
    "load_local_daily_market_data_source_capture",
    "publish_local_daily_market_data_source_capture",
]
