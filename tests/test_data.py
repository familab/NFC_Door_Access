"""Unit tests for Google Sheets data wrapper."""
import unittest
import tempfile
import os
import types
from unittest.mock import MagicMock, patch

from lib.data import GoogleSheetsData


class TestGoogleSheetsData(unittest.TestCase):
    def test_connect_success(self):
        data_client = GoogleSheetsData(creds_file="creds.json")

        mock_sheet = MagicMock()
        mock_log_sheet = MagicMock()
        mock_client = MagicMock()
        mock_client.open.side_effect = [MagicMock(sheet1=mock_sheet), MagicMock(sheet1=mock_log_sheet)]

        gspread_module = types.SimpleNamespace(authorize=MagicMock(return_value=mock_client))
        service_account_module = types.SimpleNamespace(
            ServiceAccountCredentials=types.SimpleNamespace(
                from_json_keyfile_name=MagicMock(return_value=MagicMock())
            )
        )

        with patch.dict(
            "sys.modules",
            {
                "gspread": gspread_module,
                "oauth2client": types.ModuleType("oauth2client"),
                "oauth2client.service_account": service_account_module,
            },
        ):
            connected = data_client.connect()

        self.assertTrue(connected)
        self.assertTrue(data_client.is_connected())
        self.assertIs(data_client.sheet, mock_sheet)
        self.assertIs(data_client.log_sheet, mock_log_sheet)

    def test_refresh_badge_list_no_connection(self):
        data_client = GoogleSheetsData()
        success, message = data_client.refresh_badge_list_to_csv("badges.csv")
        self.assertFalse(success)
        self.assertIn("No Google Sheets connection", message)

    def test_refresh_badge_list_to_csv_success(self):
        data_client = GoogleSheetsData()
        data_client._connected = True
        data_client.sheet = MagicMock()
        data_client.sheet.col_values.return_value = ["A", "B", "C", "D", "E"]

        with tempfile.NamedTemporaryFile(delete=False) as f:
            csv_path = f.name

        try:
            with patch("lib.data.update_last_data_connection") as data_conn_mock:
                success, message = data_client.refresh_badge_list_to_csv(csv_path)
                data_conn_mock.assert_called_once()
            self.assertTrue(success)
            self.assertIn("5 badges", message)

            with open(csv_path, "r") as f:
                contents = f.read()

            self.assertIn("A", contents)
            self.assertIn("E", contents)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_refresh_badge_list_too_few_does_not_overwrite(self):
        data_client = GoogleSheetsData()
        data_client._connected = True
        data_client.sheet = MagicMock()
        data_client.sheet.col_values.return_value = ["A", "B", "C", "D"]

        with tempfile.NamedTemporaryFile(delete=False, mode="w+") as f:
            csv_path = f.name
            f.write("OLD\n")

        try:
            success, message = data_client.refresh_badge_list_to_csv(csv_path)
            self.assertFalse(success)
            self.assertIn("Only 4 badges", message)

            with open(csv_path, "r") as f:
                contents = f.read()

            self.assertIn("OLD", contents)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_check_uid_in_sheet(self):
        data_client = GoogleSheetsData()
        data_client._connected = True
        data_client.sheet = MagicMock()
        data_client.sheet.col_values.return_value = ["ABC", "DEF"]
        with patch("lib.data.update_last_data_connection") as data_conn_mock:
            self.assertTrue(data_client.check_uid_in_sheet("abc"))
            self.assertFalse(data_client.check_uid_in_sheet("zzz"))
            self.assertGreaterEqual(data_conn_mock.call_count, 1)

    def test_log_access_success(self):
        data_client = GoogleSheetsData()
        data_client._connected = True
        data_client.log_sheet = MagicMock()

        with patch("lib.data.update_last_google_log_success") as success_mock:
            result = data_client.log_access("ABC123", "Granted")

        self.assertTrue(result)
        data_client.log_sheet.append_row.assert_called_once()
        success_mock.assert_called_once()

    def test_log_access_failure(self):
        data_client = GoogleSheetsData()
        data_client._connected = True
        data_client.log_sheet = MagicMock()
        data_client.log_sheet.append_row.side_effect = Exception("boom")

        with patch("lib.data.update_last_google_error") as err_mock:
            result = data_client.log_access("ABC123", "Granted")

        self.assertFalse(result)
        err_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
