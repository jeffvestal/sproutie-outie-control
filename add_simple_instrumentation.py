#!/usr/bin/env python3

# Read the original file
with open('/Users/jeffvestal/repos/sproutie-outie-control/packages/sproutie_outie/scripts.yaml', 'r') as f:
    lines = f.readlines()

# Find the line number for sproutie_log_event's sequence: line
insert_at = None
for i, line in enumerate(lines):
    if 'sproutie_log_event:' in line:
        # Find the sequence: line after this
        for j in range(i, min(i+20, len(lines))):
            if lines[j].strip() == 'sequence:':
                insert_at = j + 1  # Insert after sequence:
                break
        break

if insert_at:
    # Insert the debug notification
    instrumentation = [
        "      # #region agent log - ENTRY\n",
        "      - service: persistent_notification.create\n",
        "        data:\n",
        '          title: "DEBUG: sproutie_log_event ENTRY"\n',
        '          message: "batch_id={{ batch_id | default(\'NOT_PROVIDED\') }}, slot_id={{ slot_id | default(\'NOT_PROVIDED\') }}, event_type={{ event_type }}, selected_batch={{ states(\'input_text.selected_batch\') }}"\n',
        '          notification_id: "debug_log_entry"\n',
        "      # #endregion\n",
    ]
    
    lines = lines[:insert_at] + instrumentation + lines[insert_at:]
    
    # Write back
    with open('/Users/jeffvestal/repos/sproutie-outie-control/packages/sproutie_outie/scripts.yaml', 'w') as f:
        f.writelines(lines)
    
    print(f"Instrumentation added at line {insert_at}")
else:
    print("Could not find insertion point")
