import orjson
import sentry_sdk
import zstandard
from shared.reports.editable import EditableReport
from shared.reports.resources import Report

from services.redis import get_redis_connection

from .metrics import INTERMEDIATE_REPORT_SIZE
from .types import IntermediateReport

REPORT_TTL = 24 * 60 * 60


@sentry_sdk.trace
def load_intermediate_reports(upload_ids: list[int]) -> list[IntermediateReport]:
    redis = get_redis_connection()
    dctx = zstandard.ZstdDecompressor()
    intermediate_reports: list[IntermediateReport] = []

    for upload_id in upload_ids:
        key = intermediate_report_key(upload_id)
        report_dict = redis.hgetall(key)
        if not report_dict:
            intermediate_reports.append(IntermediateReport(upload_id, EditableReport()))
            continue

        # NOTE: our redis client is configured to return `bytes` everywhere,
        # so the dict keys are `bytes` as well.
        chunks = dctx.decompress(report_dict[b"chunks"]).decode(errors="replace")
        report_json = orjson.loads(dctx.decompress(report_dict[b"report_json"]))

        report = EditableReport.from_chunks(
            chunks=chunks,
            files=report_json["files"],
            sessions=report_json["sessions"],
            totals=report_json.get("totals"),
        )
        intermediate_reports.append(IntermediateReport(upload_id, report))

    return intermediate_reports


@sentry_sdk.trace
def save_intermediate_report(upload_id: int, report: Report):
    _totals, report_json = report.to_database()
    report_json = report_json.encode()
    chunks = report.to_archive().encode()
    zstd_report_json, zstd_chunks = emit_size_metrics(report_json, chunks)

    report_key = intermediate_report_key(upload_id)
    redis = get_redis_connection()
    mapping = {
        "report_json": zstd_report_json,
        "chunks": zstd_chunks,
    }
    with redis.pipeline() as pipeline:
        pipeline.hmset(report_key, mapping)
        pipeline.expire(report_key, REPORT_TTL)
        pipeline.execute()
    return


@sentry_sdk.trace
def cleanup_intermediate_reports(
    upload_ids: list[int],
):
    keys = [intermediate_report_key(upload_id) for upload_id in upload_ids]
    redis = get_redis_connection()
    redis.delete(*keys)
    return


def intermediate_report_key(upload_id: int):
    return f"intermediate-report/{upload_id}"


def emit_size_metrics(report_json: bytes, chunks: bytes) -> tuple[bytes, bytes]:
    INTERMEDIATE_REPORT_SIZE.labels(type="report_json", compression="none").observe(
        len(report_json)
    )
    INTERMEDIATE_REPORT_SIZE.labels(type="chunks", compression="none").observe(
        len(chunks)
    )

    zstd_report_json = zstandard.compress(report_json)
    zstd_chunks = zstandard.compress(chunks)

    INTERMEDIATE_REPORT_SIZE.labels(type="report_json", compression="zstd").observe(
        len(zstd_report_json)
    )
    INTERMEDIATE_REPORT_SIZE.labels(type="chunks", compression="zstd").observe(
        len(zstd_chunks)
    )

    return zstd_report_json, zstd_chunks
