"""Download of the embedded daemon's portable backup, the way ZHA hands out its network backup: an admin-only
websocket command returns the archive, and a page in the browser saves it as a file.

The backup holds `ca.key`, the device ledger and the LG account files, so it never travels outside the administrator's
own websocket connection: no download URL, no signed link and no notification. The page is an admin-only panel that
is not in the sidebar; the options flow links to it (`PANEL_PATH`).
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .backup import create
from .const import DOMAIN
from .embedded import data_dir

_LOGGER = logging.getLogger(__name__)

PANEL_PATH = f"{DOMAIN}-backup"
"""The page's address in the frontend (`/rusthinq-backup`)."""
PANEL_ELEMENT = "rusthinq-backup-panel"
STATIC_URL = f"/{DOMAIN}_static"
FRONTEND = Path(__file__).parent / "frontend"
WS_BACKUP = f"{DOMAIN}/backup"


async def async_setup(hass: HomeAssistant, version: str) -> None:
    websocket_api.async_register_command(hass, websocket_backup)
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(FRONTEND), cache_headers=False)])
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=f"{STATIC_URL}/backup-panel.js?v={version}",
        require_admin=True,
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_BACKUP})
@websocket_api.async_response
async def websocket_backup(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """rusthinq's portable backup, base64-encoded, with the file name to save it under."""
    # Not only while the daemon runs: a backup read from disk is most wanted when it cannot start.
    if not hass.config_entries.async_entries(DOMAIN):
        connection.send_error(msg["id"], "not_configured", "rusthinq is not set up")
        return
    try:
        archive = await hass.async_add_executor_job(create, data_dir(hass))
    except (OSError, ValueError) as err:
        _LOGGER.error("Could not create rusthinq backup: %s", err)
        connection.send_error(msg["id"], "backup_failed", "Could not create the backup; see the Home Assistant log")
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    connection.send_result(msg["id"], {
        "filename": f"rusthinq-backup-{stamp}.tar.gz",
        "data": base64.b64encode(archive).decode("ascii"),
    })

