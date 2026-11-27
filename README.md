<p align="center"><img src="custom_components/rusthinq/brand/icon.png" alt="" width="128" /></p>

# rusthinq for Home Assistant

Local control of LG ThinQ appliances in Home Assistant through [rusthinq](https://github.com/3735943886/rusthinq),
without an MQTT broker or an add-on. Home Assistant runs the rusthinq daemon itself; the appliances connect to it
instead of LG's cloud, and their drivers' output becomes Home Assistant devices and entities through an embedded
[IL device](https://github.com/3735943886/ildevice-homeassistant) hub.

## Requirements

- Home Assistant 2025.1.3 or later.
- LG appliances must be able to reach this Home Assistant host on TCP 443 and 8883 (or alternative ports via router
  DNAT; see [Ports](#ports)).
- For new installations, see [Connecting appliances](#connecting-appliances). Appliances already provisioned for an
  existing rusthinq can keep their CA and device setup when you [restore its backup](#restoring-from-a-backup).

## Installation

1. In Marketplace, find **rusthinq** under Integrations and download it.
2. Settings → Devices & services → Add integration → **rusthinq**, and choose:
   - **Set up a new rusthinq** for a first installation, or
   - **Restore from a backup** to keep an installation you already run elsewhere, or one whose backup you downloaded
     from this integration (see [Restoring from a backup](#restoring-from-a-backup)).

Home Assistant installs the `rusthinq` package from PyPI (the daemon binaries) with the integration. On the first start
it creates a CA and downloads the drivers: the [rusthinq-scripts](https://github.com/3735943886/rusthinq-scripts)
release this version of the integration pins. Drivers change only with a new integration release. Everything lives in
`/config/rusthinq/`, which Home Assistant backups include. `ca.key` and the LG account files are secrets.

To try a driver of your own, or another model's driver for yours, put it at the top of the drivers directory as
`/config/rusthinq/scripts/<model>.rhai`: rusthinq picks it before `drivers/<model>.rhai`. A driver update keeps files
you added; it replaces only the files of the release itself, so an edit to one of those (`drivers/<model>.rhai` that
the release ships) is lost.

To download a portable backup, open Settings → Devices & services → rusthinq → **Configure** → **Download a backup**
and follow the link to the backup page (administrators only; `/rusthinq-backup`). The browser saves the archive
directly, as ZHA's network backup does. The archive contains the daemon configuration, CA, device ledger and LG account
files needed to move the installation. In **Configure**, **Reset rusthinq data** clears those files and retained device
state, then creates a new CA; appliances may need provisioning again. Downloaded binaries and drivers are kept.

## Ports

| Listener | Default | Notes |
|---|---|---|
| HTTPS | 443 | Appliances always open 443; fixed by their firmware. |
| MQTT | 8883 | Appliances open 8883: those registered with LG already use it, and rusthinq tells appliances 8883 whatever port it listens on. If another port is used here, redirect 8883 to it. The Mosquitto add-on also uses 8883 for TLS, so pick another if it runs. |
| ThinQ1 HTTPS / ThinQ1 | 46030 / 47878 | Older ThinQ1 appliances. |
| Management API | random, 127.0.0.1 only | Used by this integration; nothing to configure. |

The setup checks port availability before saving configuration. If a port becomes unusable later, an issue is raised
in Settings → Repairs, and rusthinq keeps retrying.

The default hostname `rusthinq.lan` serves as a fallback for environments where router DNAT is not available and
traffic must be steered via local DNS overrides instead. When using router DNAT, no DNS configuration is required.

When port 443 is already in use on the host (e.g. by a reverse proxy or SSL add-on), configure rusthinq's HTTPS to
another port (such as 8443). Outbound port 443 traffic from appliances is then routed to that port as described in
[Connecting appliances](#connecting-appliances). rusthinq continues to advertise port 443 to appliances regardless of
the listener port.

## Connecting appliances

Appliances already registered in the official LG ThinQ app do not need a factory reset or re-provisioning.
Connecting them requires routing their outbound TCP 443 and 8883 traffic to this Home Assistant host: 443 to the
HTTPS port (default 443, or another port like 8443 if 443 is taken) and 8883 to the MQTT port (default 8883, or
another port if the Mosquitto add-on holds 8883). Match the destination ports the appliances use, 443 and 8883, and
translate them to rusthinq's ports; a rule on rusthinq's own port (such as 8885) never matches.

1. **Network connectivity**:
   New appliances are first set up in the official LG ThinQ app to join the Wi-Fi network and obtain a DHCP lease
   (static DHCP reservations are recommended).
2. **Route appliance traffic (leave DNS untouched)**:
   In order of preference:
   - **Router / Gateway DNAT** (Recommended; standard for Home Assistant OS and IoT VLANs):
     Forward ports 443 and 8883 from appliance IP addresses to Home Assistant (see [Router configuration examples](docs/routers.md)):
     `iptables -t nat -A PREROUTING -p tcp -m iprange --src-range <appliance_ips> --dport 443 -j DNAT --to-destination <ha_ip>:<https_port>`
     `iptables -t nat -A PREROUTING -p tcp -m iprange --src-range <appliance_ips> --dport 8883 -j DNAT --to-destination <ha_ip>:<mqtt_port>`
     (or with an ipset: `-m set --match-set lg_appliances src` in place of `-m iprange --src-range <appliance_ips>`)
   - **Host firewall** (Home Assistant Container, Supervised, Core on a custom Linux host):
     Redirect 443 and 8883 locally for appliance source addresses:
     `iptables -t nat -A PREROUTING -p tcp -m iprange --src-range <appliance_ips> --dport 443 -j REDIRECT --to-ports <https_port>`
     `iptables -t nat -A PREROUTING -p tcp -m iprange --src-range <appliance_ips> --dport 8883 -j REDIRECT --to-ports <mqtt_port>`
     (or with an ipset: `-m set --match-set lg_appliances src` in place of `-m iprange --src-range <appliance_ips>`)
   - **TLS passthrough proxy on 443** (nginx `stream` with `ssl_preread`, HAProxy, Traefik `HostSNI`):
     Send LG hostnames and connections without SNI to rusthinq unterminated. Some appliances send no SNI. Proxies
     terminating TLS do not work. 8883 still needs one of the redirects above.
3. **Let the redirected traffic through the firewall**:
   A redirect only rewrites the destination; the router still filters the result as traffic from the appliances to
   Home Assistant. Zone-based firewalls (UniFi Network zones, OPNsense or pfSense interface rules, an IoT VLAN with
   inter-VLAN blocking) drop it unless a rule allows it: allow TCP from the appliances to `<ha_ip>` on
   `<https_port>` and `<mqtt_port>`. Name rusthinq's ports here, not 443 and 8883, since filtering sees the
   translated destination. When the appliances and Home Assistant share a subnet, also masquerade (SNAT) that
   traffic at the router, so Home Assistant's replies go back through it instead of straight to the appliance.
   A blocked redirect looks like an appliance that never shows up while the DNAT rules look right.
4. **Reconnect the appliance**:
   Power-cycle the appliance or disconnect/reconnect it from Wi-Fi so it drops the existing LG session and reconnects
   through the new route. Alternatively, clear active router connection tracking with
   `conntrack -D -p tcp -s <appliance_ip>`.
5. **Automatic discovery**:
   Once the appliance connects to rusthinq, Home Assistant automatically creates the corresponding device and entities.
6. **Retain the official LG ThinQ app (Optional)**:
   Sign in to the LG account under Settings → Devices & services → rusthinq → **Configure**. Then on the appliance's
   device page in Home Assistant, press **Pair with LG**. This starts the local LG cloud bridge, keeping the official
   mobile app operational alongside Home Assistant.

## Restoring from a backup

Restoring keeps the CA the appliances trust, so none needs provisioning again. Use it to move a rusthinq you run
elsewhere into Home Assistant, or to set this integration up again from a backup it downloaded. Add the integration
with **Restore from a backup** and take the backup one of two ways:

- **Copy it from a running rusthinq** (0.2.0 or later): give its management API address, and its user and password
  if it has them. rusthinq hands the backup out only behind credentials or on a loopback bind, since it holds the CA
  key and LG tokens.
- **Upload a backup file**: one this integration downloaded (**Configure** → **Download a backup**), the dashboard's
  System → Download backup, or `sudo thinqctl backup`. Without either, an
  archive of `config.toml` and the files it names, made in its directory, works too:
  `tar czf rusthinq-export.tar.gz config.toml ca.key ca.cert devices.json account.json account.json.pairings`

The next step shows what the backup holds (host name, devices, LG account, the rusthinq version that wrote it) and
asks for this host's ports, filled in with the backup's. Then:

1. If the backup comes from another host, stop rusthinq there and keep it stopped: two daemons would answer the same
   appliances and LG account.
   A backup copied from a running rusthinq is installed only once that rusthinq no longer answers.
2. Submit the ports, changing those this host cannot open (the form says which).
3. Point the appliances' route (DNS or redirect) at this host.

The CA, the device ledger, the LG account with its pairings and the settings appliances notice (`hostname`,
`legacy_tls`, `advertise_requested_host`, `bridge_dns`, the driver topic prefix) move over, and the listener ports
are suggested. External MQTT and its
retained-topic inventory stay behind. If files in `/config/rusthinq/` differ from the backup, the confirmation step lists
them and requires an explicit choice to overwrite those included in the backup. Files absent from the backup are kept.
Replacing the CA may require provisioning appliances again.

## LG account

Settings → Devices & services → rusthinq → **Configure** signs rusthinq in to LG and out. Signing in opens LG's page;
after it, copy the address the browser ends on (`…/login/iabClose…`) back into the dialog. With an account, devices
take the names they have in the LG ThinQ app, and each device's LG bridge keeps the ThinQ app working.

## What appears

- **Each appliance**: the entities its driver describes (climate, sensors, switches…), plus
  - diagnostic: *Local connection*, *LG bridge*, *Driver* (a problem when the driver failed or is missing), *Firmware*;
  - configuration (with an LG account): *LG bridge* switch (enable/disable), *Pair with LG* and *Unpair from LG*.
- **rusthinq** (a service device): *LG account*.

Diagnostics downloads (for bug reports) leave out names, ids, addresses and account details: device ids become
`device_1`, `device_2`…, and the daemon log is scrubbed the same way.

Entities are unavailable while the daemon is not running. An appliance that is off (a washer leaves Wi-Fi when switched
off) keeps its entities across Home Assistant restarts, unavailable until it connects again.

Deleting an appliance on its device page also forgets it in rusthinq. If it is paired with LG (*Pair with LG*), that
also removes it from the LG account, even with the LG bridge switched off. That is refused while it is connected, since
it would come right back: switch it off or take it off the network first. An appliance that connects again later
appears again. An appliance that is merely offline is never forgotten.

rusthinq's own dashboard is not exposed: its management API listens on 127.0.0.1 with credentials made at each start,
and the integration covers what the dashboard offers for everyday use.

## Troubleshooting

- The daemon's own log is the logger `custom_components.rusthinq.daemon`; the integration's is
  `custom_components.rusthinq`.
- A command that cannot be carried out (the appliance is offline, a value out of range…) fires the Home Assistant
  event `ildevice_command_rejected` with the property, a code and the reason, and is logged.
- A setup that keeps retrying shows its reason on the integration card (a port in use, for example).
- An appliance that never shows up after reconnecting: check, in this order, that the router's firewall allows the
  appliances to reach `<https_port>` and `<mqtt_port>` on Home Assistant (step 3 of
  [Connecting appliances](#connecting-appliances)), that the DNAT rules match destination ports 443 and 8883, and that
  the appliance really reconnected. The daemon log (in *Download diagnostics*) names the server an appliance asked for
  when rusthinq refused or relayed its connection.
- If Home Assistant was killed, a daemon it left running is stopped on the next start.
- An *LG bridge* that keeps failing with `early eof` while the appliance is paired: in one report
  ([#17](https://github.com/3735943886/rusthinq-local/issues/17)) this followed setting the appliance up again in the
  LG ThinQ app, and *Unpair from LG* followed by *Pair with LG* brought the bridge back. Unpair removes the appliance
  from the LG account, so it is registered anew: in that report it came back under its model name instead of its name
  in the app.
- *Download diagnostics* on the integration or on an appliance gives what to attach to an issue: rusthinq's own
  diagnostics, the devices as rusthinq lists them, the daemon's last log lines, and per appliance its descriptor and
  current values. Credentials are left out.

## The `rusthinq` package

The daemon binaries are published on PyPI as [`rusthinq`](https://pypi.org/project/rusthinq/), built from rusthinq's
releases by this repository (see [wheel/README.md](wheel/README.md)); they can be used outside Home Assistant too.

## License

GPL-2.0-or-later, like rusthinq ([LICENSE](LICENSE)).
