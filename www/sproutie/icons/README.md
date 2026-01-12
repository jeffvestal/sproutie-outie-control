# Custom Icons for Sproutie Outie Control Center

Place your custom SVG icons in this directory. The following icons are needed:

## Required Icons

- `fan-exhaust.svg` - Exhaust Fan
- `fan-circulation.svg` - Top/Bottom Fans  
- `grow-light.svg` - Top/Bottom Lights
- `thermometer.svg` - Temperature sensors
- `humidity.svg` - Humidity sensors
- `camera.svg` - Camera feed
- `seedling.svg` - Tray/Crop selectors
- `target.svg` - Target setpoints
- `sproutie-logo.svg` - Header branding
- `flora-avatar.svg` - FLORA chat avatar
- `threat-indicator.svg` - Anomaly panel

## Icon Guidelines

- **Style:** Cyberpunk aesthetic - thin lines, neon glow effects
- **Colors:** Use #00f3ff (cyan) for active states, #666 for inactive
- **Size:** Optimize for 48px display size
- **Format:** SVG with inline styles preferred

## Usage in Templates

Icons can be referenced in button-card templates via:

```yaml
custom_fields:
  icon: |
    <img src="/local/sproutie/icons/fan-exhaust.svg" style="width: 48px; height: 48px;">
```

Or use as background-image in CSS:

```css
background-image: url('/local/sproutie/icons/fan-exhaust.svg');
```

