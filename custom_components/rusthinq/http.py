"""Download of the embedded daemon's portable backup, for administrators only: it holds `ca.key`, the device ledger
and the LG account files."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiohttp import web
from homeassistant.components.http import KEY_HASS_USER, HomeAssistantView
from homeassistant.core import HomeAssistant

from .backup import create
from .const import DOMAIN
from .embedded import data_dir

_LOGGER = logging.getLogger(__name__)


class BackupView(HomeAssistantView):
    url = f"/api/{DOMAIN}/backup/{{entry_id}}"
    name = f"api:{DOMAIN}:backup"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        if not request[KEY_HASS_USER].is_admin:
            raise web.HTTPForbidden()
        hass: HomeAssistant = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise web.HTTPNotFound()
        try:
            archive = await hass.async_add_executor_job(create, data_dir(hass))
        except (OSError, ValueError) as err:
            _LOGGER.error("Could not create rusthinq backup: %s", err)
            raise web.HTTPServiceUnavailable(
                text="Could not create rusthinq backup; see the Home Assistant log"
            ) from err
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return web.Response(
            body=archive,
            content_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="rusthinq-backup-{stamp}.tar.gz"'},
        )
