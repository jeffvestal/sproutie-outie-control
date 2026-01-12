"""
Home Assistant MCP Server for Sproutie Outie Control Center
Exposes HA entities as MCP tools for FLORA agent integration
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool, TextContent
import asyncio
from typing import Any, Sequence

# Initialize MCP server
mcp = FastMCP("Sproutie Outie MCP Server")

# Home Assistant API configuration
# These should be set via environment variables or config file
HA_URL = "http://homeassistant:8123"  # Adjust for your HA instance
HA_TOKEN = ""  # Set via environment variable HA_ACCESS_TOKEN


@mcp.tool()
def get_tent_status() -> dict:
    """
    Get current sensor readings from the Sproutie Outie tent.
    
    Returns:
        dict: Current temperature, humidity, and control states
    """
    # This would call Home Assistant REST API
    # For now, returns structure - implement actual HA API calls
    return {
        "tent_temp": 72.0,
        "tent_humidity": 62.0,
        "room_temp": 68.0,
        "room_humidity": 45.0,
        "fan_exhaust": False,
        "fan_top": True,
        "fan_bottom": False,
        "lights_top": True,
        "lights_bottom": True,
        "timestamp": "2026-01-05T08:00:00Z"
    }


@mcp.tool()
def set_fan_state(fan_name: str, state: bool) -> dict:
    """
    Control a fan in the Sproutie Outie tent.
    
    Args:
        fan_name: Name of the fan (exhaust, top, bottom)
        state: True to turn on, False to turn off
    
    Returns:
        dict: Confirmation of the action
    """
    # Map fan names to HA entity IDs
    fan_entities = {
        "exhaust": "switch.exhaust_fan",
        "top": "switch.top_shelf_fan",
        "bottom": "switch.bottom_shelf_fan"
    }
    
    entity_id = fan_entities.get(fan_name.lower())
    if not entity_id:
        return {
            "success": False,
            "error": f"Unknown fan: {fan_name}. Use 'exhaust', 'top', or 'bottom'"
        }
    
    # Call HA API to toggle switch
    # service = "turn_on" if state else "turn_off"
    # Call: POST /api/services/switch/{service} with {"entity_id": entity_id}
    
    return {
        "success": True,
        "fan": fan_name,
        "state": "on" if state else "off",
        "entity_id": entity_id
    }


@mcp.tool()
def set_light_state(shelf: str, state: bool) -> dict:
    """
    Control grow lights in the Sproutie Outie tent.
    
    Args:
        shelf: Shelf location (top or bottom)
        state: True to turn on, False to turn off
    
    Returns:
        dict: Confirmation of the action
    """
    light_entities = {
        "top": "switch.top_shelf_lights",
        "bottom": "switch.bottom_shelf_lights"
    }
    
    entity_id = light_entities.get(shelf.lower())
    if not entity_id:
        return {
            "success": False,
            "error": f"Unknown shelf: {shelf}. Use 'top' or 'bottom'"
        }
    
    # Call HA API to toggle switch
    # service = "turn_on" if state else "turn_off"
    # Call: POST /api/services/switch/{service} with {"entity_id": entity_id}
    
    return {
        "success": True,
        "shelf": shelf,
        "state": "on" if state else "off",
        "entity_id": entity_id
    }


@mcp.tool()
def get_crop_selection() -> dict:
    """
    Get current crop selections for Tray 1 and Tray 2.
    
    Returns:
        dict: Current crop selections
    """
    # Call HA API to get input_select values
    # GET /api/states/input_select.tray_1_crop
    # GET /api/states/input_select.tray_2_crop
    
    return {
        "tray_1": "Pea Shoots",
        "tray_2": "Sunflower",
        "timestamp": "2026-01-05T08:00:00Z"
    }


@mcp.tool()
def get_target_setpoints() -> dict:
    """
    Get target temperature and humidity setpoints.
    
    Returns:
        dict: Target values for temperature and humidity
    """
    # Call HA API to get input_number values
    # GET /api/states/input_number.target_temp
    # GET /api/states/input_number.target_humidity
    
    return {
        "target_temp": 72.0,
        "target_humidity": 65.0,
        "timestamp": "2026-01-05T08:00:00Z"
    }


if __name__ == "__main__":
    # Run the MCP server
    # This would typically be run as a service or via systemd
    import uvicorn
    uvicorn.run(mcp.app, host="0.0.0.0", port=8001)

