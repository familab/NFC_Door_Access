# Google Sheets Data Schema

[← Back to README](../README.md)

## Table of Contents
- [Overview](#overview)
- [Badge List - Access Control](#badge-list---access-control-sheet-name-exactly-badge-list---access-control)
- [Access Door Log](#access-door-log-sheet-name-exactly-access-door-log)
- [Service Account & Permissions](#service-account--permissions)
- [Local CSV fallback](#local-csv-fallback)
- [Maintenance Tips](#maintenance-tips)
- [Example Badge Sheet](#example-badge-sheet)
- [Example Access Log](#example-access-log)

This document describes the expected Google Sheets structure used by the Door Controller.

Overview
- The application uses two Google Sheets:
  - **Badge List - Access Control**: Contains authorized badge UIDs (column 1)
  - **Access Door Log**: Logs access attempts (timestamp, UID or action, status)

Badge List - Access Control (sheet name exactly: Badge List - Access Control)
- Purpose: List of authorized badge UIDs for door access
- Layout:
  - Column A (first column): UID (string). Each row is a single UID. No header row is required by the importer but you may include one; blank rows are ignored.
  - Optional metadata columns may be present (e.g., name, role), but the application only reads the first column for UIDs.
- Notes:
  - UID format: case-insensitive hex-like strings (e.g., "04A1B2C3") — the app lowercases values for comparisons.
  - Keep duplicates removed for clarity.

Access Door Log (sheet name exactly: Access Door Log)
- Purpose: Append-only log of actions and access attempts
- Layout (recommended):
  - Column A: ISO8601 timestamp (e.g., 2026-02-07 22:11:21)
  - Column B: UID or description (e.g., "04A1B2C3" or "Manual Unlock (1 hour)")
  - Column C: Status (e.g., "Granted", "Denied", "Success", "Failure")
- Notes:
  - The application appends rows; keep the sheet's sharing permissions open to the service account used by the Google API credentials.

Service Account & Permissions
- Create a Google Cloud Service Account with Sheets and Drive access and save credentials JSON as `creds.json`.
- Share both Google Sheets with the service account email (Editor role) so the application can read UIDs and append logs.

Local CSV fallback
- The application also writes a local CSV (`google_sheet_data.csv`) as a fallback when Sheets are unavailable. The CSV follows the same single-column layout (UID per row).

Maintenance Tips
- If you prefer a header row, ensure the first cell of column A is not a valid UID or trim it accordingly; the app is tolerant but will treat the first non-empty cells as UIDs.
- Avoid extremely large sheets; prefer a compact UID list.

Example Badge Sheet (first rows):

| UID |
|-----|
| 04A1B2C3 |
| 09F0E1D2 |

Example Access Log (appended rows):

| Timestamp | Badge/Action | Status |
|-----------|--------------|--------|
| 2026-02-07 22:11:21 | 04A1B2C3 | Granted |
| 2026-02-07 22:12:10 | Manual Unlock (1 hour) | Success |

If you want, I can add a small validation script to check the sheets and produce a report of missing/invalid UIDs.
