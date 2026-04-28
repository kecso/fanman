# Host prerequisites for FanMan

FanMan runs in Docker and expects **real sysfs hwmon nodes on the host kernel**. The container bind-mounts host `/sys` and `/proc`; it does **not** install kernel modules or replace motherboard firmware fan curves.

Complete these steps **on the physical machine or VM that will run the container** (the Docker host—not inside Portainer’s UI shell unless troubleshooting).

---

## 1. Supported environments

| Requirement | Notes |
|--------------|--------|
| **OS** | Linux with Docker Engine (Debian 12+, Ubuntu 22.04+, Proxmox VE 8+, etc.). FanMan does **not** target Windows or macOS hosts. |
| **Kernel** | Normal distro kernel with **hwmon** support (default on Debian/Ubuntu server kernels). |
| **Architecture** | **amd64** is primary; **arm64** may work if hwmon drivers exist for your board. |

---

## 2. Hardware monitoring kernel modules

FanMan reads temperatures and PWM nodes under `/sys/class/hwmon`. Those entries exist only if the correct drivers are loaded.

1. Install tooling:

   ```bash
   sudo apt update
   sudo apt install lm-sensors
   ```

2. Probe and load modules (interactive or automated):

   ```bash
   sudo sensors-detect
   ```

   Answer prompts to load suggested modules (e.g. `coretemp`, `k10temp`, `nct6775`, `it87`, vendor-specific drivers). Accept loading modules at boot where offered.

3. Reboot **or** load modules manually once:

   ```bash
   sudo systemctl restart systemd-modules-load
   # or modprobe the chip-specific driver listed by sensors-detect
   ```

4. Confirm sensors appear:

   ```bash
   sensors
   ```

If `sensors` shows nothing useful, fix driver/module loading **before** deploying FanMan.

---

## 3. Sysfs paths FanMan needs

FanMan never guesses paths; you configure them in `fan_curves.json` **relative** to the sysfs prefix inside the container (default `/host-sys`, which is bind-mounted from host `/sys`).

### Temperature inputs

Example discovery:

```bash
ls /sys/class/hwmon/hwmon*/temp*_input
cat /sys/class/hwmon/hwmon3/name   # identify chip
```

Paths in JSON look like `class/hwmon/hwmon0/temp1_input` (no leading slash; container joins them to `/host-sys/...`).

### PWM control

PWM sysfs nodes (`pwm*`, `pwm*_enable`) must exist **and be writable** by the container process after capabilities are applied:

```bash
ls /sys/class/hwmon/hwmon*/pwm*
ls /sys/class/hwmon/hwmon*/pwm*_enable
```

Some boards expose PWM only after BIOS setting (“manual fan control”) or vendor tooling—resolve that on the host first.

### Editing `fan_curves.json`

Copy `config/fan_curves.example.json`, map:

- One **temperature** sensor per fan curve (`temp_source`).
- Optional **RPM** inputs (`fan*_input`) if you reference them for RPM display / stall logic.
- Matching **`pwmN`** + **`pwmN_enable`** for each fan.

Wrong paths produce stale readings or harmless sysfs errors in logs until corrected.

---

## 4. Docker Engine and Compose

FanMan expects **Docker Engine** with the **Compose V2** plugin (`docker compose`, not deprecated `docker-compose` standalone unless you know what you’re doing).

```bash
sudo apt install docker.io docker-compose-v2
sudo systemctl enable --now docker
```

Portainer itself runs as a stack/container on Docker; install Docker **once** on the host, then use Portainer to deploy FanMan.

---

## 5. Permissions and Linux capabilities

Writing PWM typically requires elevated privileges inside the container.

**Recommended compose settings:**

```yaml
cap_add:
  - SYS_RAWIO
  - DAC_OVERRIDE
```

If sysfs writes still fail on your kernel (`permission denied` on `pwm*`):

1. Try adding capabilities incrementally (avoid jumping to full `privileged` unless necessary).
2. As a **last resort**, `privileged: true` grants broad host access—only on trusted LANs.

FanMan restores `pwm_enable` on graceful shutdown per `GRACEFUL_SHUTDOWN_MODE`.

---

## 6. SMART disk monitoring (optional)

If `smart_devices` lists `/dev/sda`, `/dev/nvme0n1`, etc., pass those block devices through:

```yaml
devices:
  - /dev/sda:/dev/sda
```

Ensure the device nodes exist on the host and match what you configured. Omit the `devices` section entirely if you do not use SMART.

---

## 7. Networking and firewall

- Default HTTP port inside the container: **8080** (`WEB_PORT`).
- Publish `8080:8080` (or adjust host side) and allow traffic from management VLAN / browser only.

FanMan has **no TLS** by default—terminate TLS at a reverse proxy if exposing beyond localhost.

---

## 8. SELinux / AppArmor

On distributions with strict MAC:

- Docker often applies default profiles; sysfs writes may still fail.
- You may need a local policy tweak or permissive testing—treat this as advanced troubleshooting after confirming PWM works **on the host** with appropriate privileges.

---

## 9. Deploying as a Portainer stack

Portainer deploys stacks using Docker Compose format. FanMan ships **`compose.portainer.yml`** at the repository root for this workflow.

### Before you deploy

1. Complete sections **2–5** above on the Docker host.
2. On the host filesystem, create a directory for live config (example `/opt/fanman/config`) and place **`fan_curves.json`** there (copy from `config/fan_curves.example.json` and edit paths).

### Path placeholders

The Portainer compose file uses **absolute host paths** for bind mounts so stacks work regardless of Portainer’s working directory:

```yaml
volumes:
  - /opt/fanman/config:/app/config:rw
```

Change `/opt/fanman/config` to wherever you store `fan_curves.json`.

### Git repository deployment (recommended)

The stack **`compose.portainer.yml`** pulls **`ghcr.io/kecso/fanman`** — container images for this project are published to GitHub Container Registry (see `.github/workflows/publish-image.yml`). Portainer **does not** build the Dockerfile on the host.

1. In Portainer: **Stacks → Add stack**.
2. Choose **Repository**, enter this project’s Git URL (private repos need credentials).
3. **Compose path**: `compose.portainer.yml`.
4. **Reference**: branch name (e.g. `main`).
5. Optionally enable **automatic updates** if your Portainer edition supports webhook/Git polling.

Override **`image:`** only when using a different registry or your own image build.

**GHCR pulls:** If authentication is required, add **`ghcr.io`** under Portainer **Registries**, or adjust package visibility under GitHub **Packages**.

### Web editor / upload

1. Paste contents of `compose.portainer.yml` into the stack editor.
2. Adjust `/opt/fanman/config`, devices, published ports, and `image:` tag for your host.
3. Deploy the stack.

### Image tags

Published tags include **`latest`** and version pins such as **`ghcr.io/kecso/fanman:1.0.0`**. Prefer a pinned tag over **`latest`** when you want a reproducible deployment.

### Devices and SMART

Edit or remove the `devices:` block in `compose.portainer.yml` so only disks you monitor appear.

---

## 10. Quick verification after deploy

From another machine on the LAN:

```bash
curl -s http://HOST:8080/api/health
```

Expect JSON `{"status":"ok","uptime_seconds":...}`.

Then open `http://HOST:8080/` for the dashboard.

---

## 11. Troubleshooting

| Symptom | Things to check |
|--------|-------------------|
| No temperatures | `sensors-detect`, modules loaded, paths in JSON |
| PWM unchanged | Writable `pwm*`/`pwm*_enable`, capabilities, BIOS manual fan mode |
| SMART empty | Device passthrough, `smartctl -j -a /dev/...` on host |
| Permission denied on sysfs | `DAC_OVERRIDE`, kernel sysfs permissions |

Logs: `docker logs fanman` or Portainer **Containers → fanman → Logs**.
