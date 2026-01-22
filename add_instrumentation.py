#!/usr/bin/env python3
import re

# Read the file
with open('/Users/jeffvestal/repos/sproutie-outie-control/packages/sproutie_outie/scripts.yaml', 'r') as f:
    content = f.read()

# Insert log #1: Right after "sequence:" in sproutie_log_event
pattern1 = r'(  sproutie_log_event:.*?sequence:\n)'
replacement1 = r'\1      # #region agent log\n      - service: shell_command.log_json\n        data:\n          msg: \'{"location":"scripts.yaml:51","message":"sproutie_log_event ENTRY","data":{"batch_id_provided":"{{ batch_id | default(\'\'NOT_PROVIDED\'\') }}","slot_id_provided":"{{ slot_id | default(\'\'NOT_PROVIDED\'\') }}","event_type":"{{ event_type | default(\'\'NOT_PROVIDED\'\') }}","selected_batch_state":"{{ states(\'\'input_text.selected_batch\'\') }}"},"timestamp":{{ as_timestamp(now()) * 1000 | int }},"sessionId":"debug-session","hypothesisId":"A"}\'\n      # #endregion\n'
content = re.sub(pattern1, replacement1, content, count=1, flags=re.DOTALL)

# Insert log #2: After target_batch variable is set
pattern2 = r'(          target_batch: >.*?endif %}\n)'
replacement2 = r'\1      # #region agent log\n      - service: shell_command.log_json\n        data:\n          msg: \'{"location":"scripts.yaml:86","message":"After variable resolution","data":{"target_slot":"{{ target_slot }}","target_batch":"{{ target_batch }}","event_type":"{{ event_type }}"},"timestamp":{{ as_timestamp(now()) * 1000 | int }},"sessionId":"debug-session","hypothesisId":"B,C"}\'\n      # #endregion\n'
content = re.sub(pattern2, replacement2, content, count=1, flags=re.DOTALL)

# Insert log #3: Inside the else block, right before the repeat loop for non-Phase-Change events
pattern3 = r'(        else:\n)(          - repeat:)'
replacement3 = r'\1      # #region agent log\n          - service: shell_command.log_json\n            data:\n              msg: \'{"location":"scripts.yaml:167","message":"Entering ELSE branch for non-PhaseChange events","data":{"event_type":"{{ event_type }}","target_batch":"{{ target_batch }}"},"timestamp":{{ as_timestamp(now()) * 1000 | int }},"sessionId":"debug-session","hypothesisId":"C"}\'\n          # #endregion\n\2'
content = re.sub(pattern3, replacement3, content, count=1)

# Insert log #4: After the condition check inside the repeat loop (else branch)
pattern4 = r'(                      value_template: >.*?false\n                        {% endif %}\n)(                  then:)'
replacement4 = r'\1      # #region agent log\n                    - service: shell_command.log_json\n                      data:\n                        msg: \'{"location":"scripts.yaml:181","message":"Slot match check","data":{"repeat_item":"{{ repeat.item }}","condition_result":"{{ \'MATCH\' if ((this_slot_raw not in [\'\'unknown\'\', \'\'unavailable\'\', \'\'Empty\'\', \'\'\'\']) and ((this_slot_raw | from_json(default={})).id | string | trim == target_batch | string | trim)) else \'\'NO_MATCH\'\' }}"},"timestamp":{{ as_timestamp(now()) * 1000 | int }},"sessionId":"debug-session","hypothesisId":"C,D"}\'\n                    # #endregion\n\2'
content = re.sub(pattern4, replacement4, content, count=1, flags=re.DOTALL)

# Insert log #5: Right after updated_json is created (in the else branch)
pattern5 = r'(                        updated_json: >.*?"history": {{ \(history \+ \[new_event \| from_json\]\) \| to_json }}\n                          }\n)'
replacement5 = r'\1      # #region agent log\n                    - service: shell_command.log_json\n                      data:\n                        msg: \'{"location":"scripts.yaml:205","message":"About to write updated JSON","data":{"repeat_item":"{{ repeat.item }}","updated_json_length":{{ updated_json | length }},"history_count":{{ (history + [new_event | from_json]) | length }}},"timestamp":{{ as_timestamp(now()) * 1000 | int }},"sessionId":"debug-session","hypothesisId":"D,E"}\'\n                    # #endregion\n'
content = re.sub(pattern5, replacement5, content, count=1, flags=re.DOTALL)

# Write the file back
with open('/Users/jeffvestal/repos/sproutie-outie-control/packages/sproutie_outie/scripts.yaml', 'w') as f:
    f.write(content)

print("Instrumentation added successfully!")
