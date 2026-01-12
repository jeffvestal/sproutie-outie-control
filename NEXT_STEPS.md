# Next Steps for Home Assistant Configuration

## Files Updated

✅ `packages/sproutie_outie/views/command_center.yaml` - Added title and path
✅ `packages/sproutie_outie/views/flora_chat.yaml` - Added title and path  
✅ `configuration_example.yaml` - Added lovelace configuration

## Steps to Complete

### 1. Update your HA configuration.yaml

Your `/homeassistant/configuration.yaml` should now include:

```yaml
# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

# Enable packages
homeassistant:
  packages: !include_dir_named packages

# Load Lovelace in YAML mode
lovelace:
  mode: yaml
  resources:
    - url: /hacsfiles/button-card/button-card.js
      type: module
    - url: /hacsfiles/lovelace-card-mod/card-mod.js
      type: module
    - url: /hacsfiles/lovelace-layout-card/layout-card.js
      type: module
    - url: /hacsfiles/mini-graph-card/mini-graph-card-bundle.js
      type: module

# Standard includes
automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

# Your existing eufy config
eufy:
  username: kegsofduff@gmail.com
  password: ....
```

### 2. Upload updated files

```bash
# Upload updated view files
rsync -avz -e ssh packages/sproutie_outie/views/ kegsofduff@192.168.1.232:/homeassistant/packages/sproutie_outie/views/
```

### 3. Restart Home Assistant

After updating configuration.yaml and uploading the files:
- Go to **Settings → System → Restart**

### 4. Access the dashboard

After restart:
- Go to **Overview** in the sidebar
- The dashboard should now load without errors!

## Troubleshooting

If you still see errors:

1. **Check logs:**
   - Settings → System → Logs

2. **Verify entities exist:**
   - Go to Developer Tools → States
   - Search for: `sensor.sproutie_outie_internal_temp`
   - If missing, you'll need to create or map your actual sensor entities

3. **Check button-card templates loaded:**
   - The templates should now be recognized from `ui-lovelace.yaml`

4. **Missing entities to create:**
   - `camera.tent_inside_placeholder` - Create a dummy camera or comment out that card
   - All switch entities (exhaust_fan, etc.) - Map to your actual devices

## What's Working Now

✅ Package structure
✅ Custom cards installed
✅ Input helpers created
✅ Templates defined in correct location
✅ Lovelace YAML mode configured
✅ Icons uploaded

## Still TODO

- Map actual sensor entities to the Sproutie names
- Set up Elasticsearch integration
- Configure MCP Server integration
- Create FLORA agent
- Set up REST commands with ES credentials

