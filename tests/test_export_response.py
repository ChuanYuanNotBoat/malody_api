import io
import sys
from pathlib import Path
from unittest import TestCase

import pandas as pd
from openpyxl import load_workbook

ROOT_PARENT = Path(__file__).resolve().parents[2]
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from malody_api.utils.export_response import _dataframe_to_xlsx_bytes  # noqa: E402


class TestExportResponseXlsxFormatting(TestCase):
    def test_dataframe_to_xlsx_bytes_autosizes_columns_and_rows(self):
        long_text = "x" * 120
        df = pd.DataFrame(
            [
                {"name": "Alice", "note": long_text},
                {"name": "Bob", "note": "short"},
            ]
        )

        stream = _dataframe_to_xlsx_bytes(df, "charts")
        workbook = load_workbook(io.BytesIO(stream.getvalue()))
        worksheet = workbook["charts"]

        self.assertGreaterEqual(float(worksheet.column_dimensions["A"].width or 0), 10.0)
        self.assertGreaterEqual(float(worksheet.column_dimensions["B"].width or 0), 10.0)
        self.assertGreater(float(worksheet.row_dimensions[2].height or 0), 15.0)
