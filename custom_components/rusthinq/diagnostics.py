"""Diagnostics for bug reports: what Home Assistant sees of rusthinq, and rusthinq's own `/api/diagnostics`.

Diagnostics files end up attached to public issues, so nothing in them may identify the person or the appliances.
Fields that carry such values are redacted by name (`TO_REDACT`). Device ids, which rusthinq also uses as map keys,
topic segments and log text, become stable pseudonyms (`device_1`, ...). Every remaining string, including the daemon
log, is scrubbed of the known names and ids and of anything shaped like an IP or MAC address, an e-mail address, a
UUID or a long hex token.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import RusthinqConfigEntry
from .client import ManagementError
from .const import CONF_URL, DOMAIN

TO_REDACT = {
    # Entry data and the imported daemon settings (`migrate.Imported.settings`).
    CONF_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    "hostname",
    "bridge_dns",
    # Appliances: rusthinq's names (and the descriptor label taken from them), plus whatever identifying field a
    # payload may carry.
    "name",
    "label",
    "serial",
    "serialNumber",
    "mac",
    "macAddress",
    "ip",
    "ipAddress",
    "ssid",
    "email",
    "userId",
}
ACCOUNT_TO_REDACT = {"country", "error"}
"""The LG account (`/api/cloud`): which country it is in, and LG's own error text."""

_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),  # e-mail
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE),  # UUID
    re.compile(r"\b[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}\b", re.IGNORECASE),  # MAC
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),  # IPv4
    re.compile(r"\b(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}\b", re.IGNORECASE),  # IPv6, full
    re.compile(r"(?<![\w:])(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?(?![\w:])",
               re.IGNORECASE),  # IPv6, compressed
    re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE),  # long hex: ids, tokens, serials
)


class _Scrubber:
    """Pseudonymises device ids and removes other identifying text, everywhere in a JSON-like value."""

    def __init__(self, devices: Iterable[str], values: Iterable[str]) -> None:
        self._aliases = {device: f"device_{n}" for n, device in enumerate(sorted(devices), 1)}
        # Longest first, so an id that contains another is replaced whole.
        known = {**{value: REDACTED for value in values if value}, **self._aliases}
        self._known = [(re.compile(rf"(?<!\w){re.escape(value)}(?!\w)"), replacement)
                       for value, replacement in sorted(known.items(), key=lambda item: len(item[0]), reverse=True)]

    def alias(self, device: str) -> str:
        return self._aliases.get(device) or self.text(device)

    def text(self, text: str) -> str:
        for value, replacement in self._known:
            text = value.sub(replacement, text)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def data(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {self.text(key) if isinstance(key, str) else key: self.data(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self.data(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value


def _scrubber(entry: RusthinqConfigEntry) -> _Scrubber:
    client = entry.runtime_data.client
    values: list[str] = []
    for info in client.devices.values():
        if isinstance(name := (info or {}).get("name"), str):
            values.append(name)
    settings = entry.data.get("settings") or {}
    if isinstance(hostname := settings.get("hostname"), str):
        values.append(hostname)
    values.extend(server for server in settings.get("bridge_dns") or () if isinstance(server, str))
    return _Scrubber(client.devices, values)


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: RusthinqConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    client = data.client
    try:
        rusthinq = await client.diagnostics()
    except ManagementError as err:
        rusthinq = {"error": str(err)}
    daemon = data.daemon
    scrub = _scrubber(entry)
    return scrub.data(async_redact_data({
        "entry": dict(entry.data),
        "daemon": {"version": daemon.version, "log": list(daemon.lines)},
        "connected": client.connected.is_set(),
        "features": client.features,
        "account": async_redact_data(client.account, ACCOUNT_TO_REDACT),
        "devices": client.devices,
        "rusthinq": rusthinq,
    }, TO_REDACT))


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: RusthinqConfigEntry, device_entry: DeviceEntry
) -> dict[str, Any]:
    client = entry.runtime_data.client
    devices = sorted(ident for domain, ident in device_entry.identifiers
                     if domain == DOMAIN and ident != entry.entry_id)
    scrub = _scrubber(entry)
    return {
        scrub.alias(device): scrub.data(async_redact_data({
            "rusthinq": client.devices.get(device),
            "descriptor": client.descriptor(device),
            "retained": client.retained_values(device),
        }, TO_REDACT))
        for device in devices
    }
