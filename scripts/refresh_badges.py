"""Refresh badge list from Google Sheets and write to local CSV."""
import sys

from src_serviceconfig import config
from src_servicedata import GoogleSheetsData
from src_servicelogging_utils import get_logger


def main() -> int:
    logger = get_logger()
    data_client = GoogleSheetsData()

    if not data_client.connect():
        logger.error("Failed to connect to Google Sheets")
        return 1

    success, message = data_client.refresh_badge_list_to_csv(config["CSV_FILE"])
    if success:
        logger.info(f"Badge refresh job completed: {message}")
        return 0

    logger.error(f"Badge refresh job failed: {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
