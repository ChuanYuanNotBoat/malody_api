import io
from typing import BinaryIO

import pandas as pd
from fastapi.responses import StreamingResponse


SUPPORTED_EXPORT_FORMATS = {"csv", "xlsx"}


def normalize_export_format(output_format: str) -> str:
    normalized = (output_format or "csv").strip().lower()
    if normalized not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError("format must be csv or xlsx")
    return normalized


def _dataframe_to_csv_bytes(df: pd.DataFrame) -> BinaryIO:
    stream = io.BytesIO()
    df.to_csv(stream, index=False, encoding="utf-8-sig")
    stream.seek(0)
    return stream


def _dataframe_to_xlsx_bytes(df: pd.DataFrame, sheet_name: str) -> BinaryIO:
    last_error: Exception | None = None
    for engine in ("openpyxl", "xlsxwriter", None):
        stream = io.BytesIO()
        try:
            with pd.ExcelWriter(stream, engine=engine) as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            stream.seek(0)
            return stream
        except Exception as exc:  # pragma: no cover - fallback path
            last_error = exc
            continue

    raise RuntimeError("Unable to write xlsx bytes") from last_error


def build_dataframe_download_response(
    df: pd.DataFrame,
    base_filename: str,
    output_format: str,
    sheet_name: str = "data",
) -> StreamingResponse:
    normalized = normalize_export_format(output_format)
    if normalized == "csv":
        stream = _dataframe_to_csv_bytes(df)
        media_type = "text/csv; charset=utf-8"
    else:
        stream = _dataframe_to_xlsx_bytes(df, sheet_name)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    filename = f"{base_filename}.{normalized}"
    return StreamingResponse(
        stream,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
