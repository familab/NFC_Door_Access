import csv
from datetime import datetime

csv_path = r'c:\Users\theef\Documents\coding_projects\familab\badge_scanner2\logs\Access Door Log - Sheet1.csv'
output_dir = r'c:\Users\theef\Documents\coding_projects\familab\badge_scanner2\logs'
output_file = f'{output_dir}\\door_controller_action.log'

all_lines = []

with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        date_str = row['date']
        who = row['who']
        status = row['status']

        # Parse date: "3/22/2025 14:56" -> "2025-03-22 14:56:00"
        try:
            dt = datetime.strptime(date_str, '%m/%d/%Y %H:%M')
            # Format as YYYY-MM-DD HH:MM:SS
            timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            print(f"Error parsing {date_str}: {e}")
            continue

        # Format the log line like: "2026-02-08 20:31:18 - door_action - INFO - ..."
        if who.startswith('Manual'):
            # Manual actions like "Manual Unlock (1 hour)", "Manual Lock"
            log_line = f"{timestamp} - door_action - INFO - {who} - Status: {status}\n"
        else:
            # Badge scan
            log_line = f"{timestamp} - door_action - INFO - Badge Scan - Badge: {who} - Status: {status}\n"

        all_lines.append(log_line)

# Write all lines to a single file
with open(output_file, 'w') as f:
    f.writelines(all_lines)

print(f"Created {output_file} with {len(all_lines)} lines")
