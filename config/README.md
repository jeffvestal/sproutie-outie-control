# Site configuration

`site.yaml` is the canonical, committed identity map for physical devices.  Brain-era code
must use a role such as `top_lights` or `exhaust`; it must never embed a Home Assistant entity
ID.  The remaining v1 Home Assistant YAML is a temporary exception: issue #6 deliberately does
not rewrite it because issue #7/#10 retire that layer.  Do not add new v1 references.

## Verify the live map

Set credentials in the shell (never in this repository), then run:

```sh
export HA_URL='http://192.168.1.232:8123'
export HA_ACCESS_TOKEN='…'
python3 scripts/verify_devices.py
```

The command checks every configured switch and power sensor. It exits non-zero if a required,
enabled role is missing, unavailable, or has a non-numeric power reading. The deliberate disabled
`tent-2-sim` entry proves that an offline extra zone is reported as `online: false` without
masking a real tent failure.

## Re-pair a device

1. In Home Assistant, open **Settings → Devices & services → Entities**, locate the physical
   TP-Link socket, and set its entity ID to the value already assigned to that role in
   `site.yaml`.  The entity registry stores this explicit ID; do not accept an auto-suffixed
   replacement such as `_2`.
2. Confirm the socket’s Kasa alias against `kasa_alias` and run the verifier.
3. Update only the corresponding role in `site.yaml` if the deliberate new entity ID differs.
   Update its associated power/energy/voltage/current entities at the same time.
4. Toggle and measure one relay at a time, restore its original state, record the measured
   watts and settle time in the issue, then replace the `expected_watts_on` estimate.

Do not create `hardware/entity-map.yaml` (or a second identity map) again.
