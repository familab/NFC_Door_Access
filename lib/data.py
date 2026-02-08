"""Google Sheets data access wrapper."""
from typing import Optional, List, Tuple
import time
import csv
import os
import tempfile

from .config import config
from .logging_utils import (
    get_logger,
    update_last_badge_download,
    update_last_data_connection,
    update_last_google_log_success,
    update_last_google_error,
)


class GoogleSheetsData:
    """Wrapper for Google Sheets access with error handling."""

    def __init__(
        self,
        creds_file: Optional[str] = None,
        badge_sheet_name: Optional[str] = None,
        log_sheet_name: Optional[str] = None,
    ):
        self.creds_file = creds_file or config["CREDS_FILE"]
        self.badge_sheet_name = badge_sheet_name or config["BADGE_SHEET_NAME"]
        self.log_sheet_name = log_sheet_name or config["LOG_SHEET_NAME"]
        self.sheet = None
        self.log_sheet = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to Google Sheets using service account credentials."""
        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials

            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.creds_file, scope)
            client = gspread.authorize(creds)

            self.sheet = client.open(self.badge_sheet_name).sheet1
            self.log_sheet = client.open(self.log_sheet_name).sheet1
            self._connected = True
            get_logger().info("Google Sheets connection established")
            update_last_data_connection()

            return True
        except ModuleNotFoundError as e:
            get_logger().warning(
                f"Google Sheets libraries not available: {e}. Continuing without Google Sheets."
            )
        except Exception as e:
            get_logger().warning(f"Failed to connect to Google Sheets: {e}")
            get_logger().warning("Will attempt to use local CSV fallback")

        self.sheet = None
        self.log_sheet = None
        self._connected = False
        return False

    def is_connected(self) -> bool:
        return self._connected and self.sheet is not None

    def get_badge_uids(self, normalize_lower: bool = False) -> List[str]:
        """Fetch badge UIDs from the badge sheet."""
        if not self.is_connected():
            raise RuntimeError("Google Sheets not connected")
        # or self.sheet.get_all_values()
        uids = [cell.strip() for cell in self.sheet.col_values(1) if cell]
        update_last_data_connection()

        if normalize_lower:
            return [u.lower() for u in uids]
        return uids

    def refresh_badge_list_to_csv(self, csv_file: str) -> Tuple[bool, str]:
        """Refresh badge list and persist to CSV."""
        if not self.is_connected():
            get_logger().warning("Badge refresh requested but Google Sheets not connected")
            update_last_badge_download(success=False)
            return False, "No Google Sheets connection"

        try:
            uids = self.get_badge_uids(normalize_lower=False)

            if len(uids) < 5:
                get_logger().warning(
                    f"Badge refresh rejected: only {len(uids)} entries (minimum 5 required)"
                )
                update_last_badge_download(success=False)
                return False, f"Only {len(uids)} badges"

            try:
                directory = os.path.dirname(csv_file) or "."
                with tempfile.NamedTemporaryFile(
                    mode="w", newline="", delete=False, dir=directory
                ) as tf:
                    writer = csv.writer(tf)
                    for u in uids:
                        writer.writerow([u])
                    temp_path = tf.name

                os.replace(temp_path, csv_file)
            except Exception as e:
                get_logger().warning(f"Failed to write local CSV fallback: {e}")
                update_last_badge_download(success=False)
                try:
                    if "temp_path" in locals() and os.path.exists(temp_path):
                        os.unlink(temp_path)
                except Exception:
                    pass
                return False, "Failed to write CSV"

            get_logger().info(f"Badge list refreshed: {len(uids)} entries")
            return True, f"{len(uids)} badges"
        except Exception as e:
            get_logger().exception("Badge refresh failed")
            update_last_badge_download(success=False)
            return False, str(e)

    def check_uid_in_sheet(self, uid_hex: str) -> bool:
        """Check if a UID exists in the badge sheet."""
        uids = self.get_badge_uids(normalize_lower=True)
        return uid_hex.lower() in uids

    def log_access(self, uid: str, status: str) -> bool:
        """Append an access event to the log sheet."""
        if not self._connected or self.log_sheet is None:
            return False

        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            self.log_sheet.append_row([timestamp, uid, status])
            update_last_google_log_success()
            get_logger().debug(f"Successfully logged to Google Sheets: {uid} - {status}")
            return True
        except Exception as e:
            update_last_google_error(str(e))
            get_logger().warning(f"Failed to log to Google Sheets: {e}")
            return False
