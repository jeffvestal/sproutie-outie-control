contents = """# Sproutie OS v2.1 - Scripts
# Logic and External Connectors

rest_command:
  sproutie_push_to_elastic:
    url: !secret es_url_endpoint
    method: POST
    headers:
      Authorization: !secret es_api_key
      Content-Type: "application/json"
    payload: |
      {
        "@timestamp": "{{ timestamp }}",
        "event.dataset": "sproutie.events",
        "sproutie": {
          "batch_id": "{{ batch_id }}",
          "slot_id": "{{ slot_id }}",
          "event_type": "{{ event_type }}",
          "detail": "{{ detail }}",
          "photo_url": "{{ photo_url }}",
          "environment": {
            "temp": {{ temp }},
            "humidity": {{ humidity }}
          }
        }
      }
    content_type: "application/json"

script:
  sproutie_log_event:
    alias: "Sproutie Log Event"
    description: "Master script for logging events to Elasticsearch"
    fields:
      batch_id:
        description: "The batch ID (Tray ID)"
        example: "1768093958"
      slot_id:
        description: "Optional representative slot ID (A1-B8)"
        example: "A1"
      event_type:
        description: "Event type (Water, Phase Change, Issue, Harvest, Note, etc.)"
        example: "Phase Change"
      detail:
        description: "Event detail/description"
        example: "Blackout"
      take_photo:
        description: "Whether to capture a photo snapshot"
        default: false
    sequence:
      - variables:
          target_slot: >
            {% if slot_id is defined and slot_id != '' %}
              {{ slot_id }}
            {% else %}
              {% set slots = ['a1','a2','a3','a4','a5','a6','a7','a8','b1','b2','b3','b4','b5','b6','b7','b8'] %}
              {% set ns = namespace(slot='') %}
              {% for s in slots %}
                {% if ns.slot == '' %}
                  {% set raw = states('input_text.slot_' ~ s ~ '_data') %}
                  {% if raw not in ['unknown', 'unavailable', 'Empty', ''] %}
                    {% if (raw | from_json(default={})).id == batch_id %}
                      {% set ns.slot = s | upper %}
                    {% endif %}
                  {% endif %}
                {% endif %}
              {% endfor %}
              {{ ns.slot }}
            {% endif %}
          target_batch: >
            {% if batch_id is defined and batch_id != '' %}
              {{ batch_id }}
            {% else %}
              {% set raw = states('input_text.slot_' ~ (target_slot | lower) ~ '_data') %}
              {% if raw not in ['unknown', 'unavailable', 'Empty', ''] %}
                {{ (raw | from_json(default={})).id }}
              {% else %}
                unknown
              {% endif %}
            {% endif %}
          event_detail: >
            {% if event_type == 'Water' %}
              {{ states('input_select.watering_type') }}
            {% elif event_type == 'Note' %}
              {{ states('input_text.event_note') }}
            {% else %}
              {{ detail | default('') }}
            {% endif %}
          current_temp: "{{ states('sensor.sproutie_outie_internal_temp') | float(0) }}"
          current_humidity: "{{ states('sensor.sproutie_outie_internal_humidity') | float(0) }}"
          photo_url: ""
      - if:
          - condition: template
            value_template: "{{ take_photo | default(false) and target_slot != '' }}"
        then:
          - variables:
              camera_entity: >
                {% if target_slot[0] | upper == 'A' %}
                  camera.sproutie_outie_top_eyes
                {% else %}
                  camera.sproutie_outie_bottom_eyes
                {% endif %}
              timestamp_str: "{{ now().strftime('%Y%m%d_%H%M%S') }}"
              filename: "{{ target_slot | lower }}_{{ timestamp_str }}.jpg"
              snapshot_path: "snapshots/{{ filename }}"
          - service: camera.snapshot
            target:
              entity_id: "{{ camera_entity }}"
            data:
              filename: "{{ snapshot_path }}"
          - variables:
              photo_url: "/local/snapshots/{{ filename }}"
      - if:
          - condition: template
            value_template: "{{ event_type == 'Phase Change' }}"
        then:
          - repeat:
              for_each: ['a1','a2','a3','a4','a5','a6','a7','a8','b1','b2','b3','b4','b5','b6','b7','b8']
              sequence:
                - variables:
                    this_slot_raw: "{{ states('input_text.slot_' ~ repeat.item ~ '_data') }}"
                - if:
                    - condition: template
                      value_template: >
                        {% if this_slot_raw not in ['unknown', 'unavailable', 'Empty', ''] %}
                          {{ (this_slot_raw | from_json(default={})).id | string == target_batch | string }}
                        {% else %}
                          false
                        {% endif %}
                  then:
                    - variables:
                        d: "{{ this_slot_raw | from_json(default={}) }}"
                        updated_json: >
                          {
                            "crop": "{{ d.get('crop', '') }}",
                            "id": "{{ d.get('id', '') }}",
                            "planted": "{{ d.get('planted', '') }}",
                            "container": "{{ d.get('container', '') }}",
                            "phase": "{{ event_detail }}",
                            "seed_weight": {{ d.get('seed_weight', 0) }},
                            "soak_time": {{ d.get('soak_time', 0) }},
                            "substrate": "{{ d.get('substrate', '') }}",
                            "notes": "{{ d.get('notes', '') }}"
                          }
                    - service: input_text.set_value
                      target:
                        entity_id: "input_text.slot_{{ repeat.item }}_data"
                      data:
                        value: "{{ updated_json }}"
      - service: rest_command.sproutie_push_to_elastic
        data:
          timestamp: "{{ now().isoformat() }}"
          batch_id: "{{ target_batch }}"
          slot_id: "{{ target_slot }}"
          event_type: "{{ event_type }}"
          detail: "{{ event_detail }}"
          photo_url: "{{ photo_url }}"
          temp: "{{ current_temp }}"
          humidity: "{{ current_humidity }}"
      - service: browser_mod.notification
        data:
          message: "{{ event_type }} logged for Batch {{ target_batch }}"
          duration: 3000
      - service: input_text.set_value
        target:
          entity_id: input_text.event_note
        data:
          value: ""

  toggle_inspection_mode:
    alias: "Toggle Inspection Mode"
    description: "Save scene, kill grow lights, turn on Aux light"
    sequence:
      - service: scene.create
        data:
          scene_id: "sproutie_pre_inspection_scene"
          snapshot_entities:
            - switch.top_shelf_lights
            - switch.bottom_shelf_lights
            - switch.aux_light
            - input_boolean.inspection_mode
      - service: switch.turn_off
        target:
          entity_id:
            - switch.top_shelf_lights
            - switch.bottom_shelf_lights
      - service: switch.turn_on
        target:
          entity_id: switch.aux_light
      - service: input_boolean.toggle
        target:
          entity_id: input_boolean.inspection_mode

  sproutie_plant_batch:
    alias: "Plant Batch"
    description: "Creates a new batch in the selected slot"
    fields:
      slot_id:
        description: "The slot ID (A1-A8, B1-B8)"
        example: "A1"
    sequence:
      - variables:
          target_slot: "{{ slot_id | default(states('input_text.selected_slot')) }}"
          batch_id: "{{ now().timestamp() | int(0) }}"
          crop: "{{ states('input_select.planting_preset') }}"
          container: "{{ states('input_select.container_type') }}"
          seed_weight: "{{ states('input_number.seed_weight') | int(0) }}"
          plant_date: "{{ states('input_datetime.batch_plant_date') | default(now().strftime('%Y-%m-%d')) }}"
          payload: >
            {
              "crop": "{{ crop }}",
              "id": "{{ batch_id }}",
              "planted": "{{ plant_date }}",
              "container": "{{ container }}",
              "phase": "Germination",
              "seed_weight": {{ seed_weight }},
              "soak_time": 0,
              "substrate": "Soil",
              "notes": ""
            }
      - service: input_text.set_value
        target:
          entity_id: "input_text.slot_{{ target_slot | lower }}_data"
        data:
          value: "{{ payload }}"
      - service: rest_command.sproutie_push_to_elastic
        data:
          timestamp: "{{ now().isoformat() }}"
          batch_id: "{{ batch_id }}"
          slot_id: "{{ target_slot }}"
          event_type: "Planted"
          detail: "{{ crop }} planted in {{ container }}"
          photo_url: ""
          temp: "{{ states('sensor.sproutie_outie_internal_temp') | float(0) }}"
          humidity: "{{ states('sensor.sproutie_outie_internal_humidity') | float(0) }}"
      - service: input_text.set_value
        target:
          entity_id: input_text.selected_slot
        data:
          value: ""
      - service: browser_mod.notification
        data:
          message: "New {{ crop }} batch planted in {{ target_slot }}"
          duration: 5000

  sproutie_harvest_batch:
    alias: "Harvest Batch"
    description: "Harvests and clears all slots in a batch"
    fields:
      batch_id:
        description: "The Batch ID to harvest"
        example: "1768093958"
    sequence:
      - variables:
          harvest_weight: "{{ states('input_number.harvest_weight') | float(0) }}"
          harvest_note: "{{ states('input_text.event_note') }}"
          metadata: >-
            {% set slots = ['a1','a2','a3','a4','a5','a6','a7','a8','b1','b2','b3','b4','b5','b6','b7','b8'] %}
            {% set ns = namespace(found=false, crop='Unknown', seed_w=1, slot='') %}
            {% for s in slots %}
              {% if not ns.found %}
                {% set raw = states('input_text.slot_' ~ s ~ '_data') %}
                {% if raw not in ['unknown', 'unavailable', 'Empty', ''] %}
                  {% set d = raw | from_json(default={}) %}
                  {% if d.id | string == batch_id | string %}
                    {% set ns.found = true %}
                    {% set ns.crop = d.get('crop', 'Unknown') %}
                    {% set ns.seed_w = d.get('seed_weight', 1) %}
                    {% set ns.slot = s | upper %}
                  {% endif %}
                {% endif %}
              {% endif %}
            {% endfor %}
            {{ {'crop': ns.crop, 'seed_weight': ns.seed_w, 'representative_slot': ns.slot} | to_json }}
          meta: "{{ metadata | trim | from_json(default={}) }}"
          yield_ratio: "{{ (harvest_weight | float(0) / meta.get('seed_weight', 1) | float(1)) | round(2) if meta.get('seed_weight', 1) | float(1) > 0 else 0 }}"
      - service: rest_command.sproutie_push_to_elastic
        data:
          timestamp: "{{ now().isoformat() }}"
          batch_id: "{{ batch_id }}"
          slot_id: "{{ meta.get('representative_slot', 'Unknown') }}"
          event_type: "Harvested"
          detail: "Yield: {{ harvest_weight }}g ({{ yield_ratio }}x). Note: {{ harvest_note }}"
          photo_url: ""
          temp: "{{ states('sensor.sproutie_outie_internal_temp') | float(0) }}"
          humidity: "{{ states('sensor.sproutie_outie_internal_humidity') | float(0) }}"
      - repeat:
          for_each: ['a1','a2','a3','a4','a5','a6','a7','a8','b1','b2','b3','b4','b5','b6','b7','b8']
          sequence:
            - variables:
                this_slot_raw: "{{ states('input_text.slot_' ~ repeat.item ~ '_data') }}"
            - if:
                - condition: template
                  value_template: >
                    {% if this_slot_raw not in ['unknown', 'unavailable', 'Empty', ''] %}
                      {{ (this_slot_raw | from_json(default={})).id | string == batch_id | string }}
                    {% else %}
                      false
                    {% endif %}
              then:
                - service: input_text.set_value
                  target:
                    entity_id: "input_text.slot_{{ repeat.item }}_data"
                  data:
                    value: "Empty"
      - service: input_number.set_value
        target:
          entity_id: input_number.harvest_weight
        data:
          value: 0
      - service: input_text.set_value
        target:
          entity_id: input_text.event_note
        data:
          value: ""
      - service: browser_mod.notification
        data:
          message: "Harvested {{ meta.get('crop', 'Unknown') }} (Batch {{ batch_id }}): {{ harvest_weight }}g"
          duration: 5000

  sproutie_advance_phase:
    alias: "Advance to Next Phase"
    description: "Transitions batch to the next growth phase"
    fields:
      batch_id:
        description: "The batch ID"
        example: "1768093958"
    sequence:
      - variables:
          next_phase: "{{ states('input_select.phase_transition') }}"
      - service: script.sproutie_log_event
        data:
          batch_id: "{{ batch_id }}"
          event_type: "Phase Change"
          detail: "{{ next_phase }}"
          take_photo: true

  sproutie_log_issue:
    alias: "Log Issue"
    description: "Logs an issue for a batch"
    fields:
      batch_id:
        description: "The batch ID"
        example: "1768093958"
    sequence:
      - variables:
          issue_detail: "{{ states('input_text.issue_note') }}"
      - service: script.sproutie_log_event
        data:
          batch_id: "{{ batch_id }}"
          event_type: "Issue"
          detail: "{{ issue_detail }}"
          take_photo: true
      - service: input_text.set_value
        target:
          entity_id: input_text.issue_note
        data:
          value: ""
\"\"\"

with open('packages/sproutie_outie/scripts.yaml', 'w') as f:
    f.write(contents)
