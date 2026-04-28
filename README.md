# FanMan

FanMan runs in a single Docker container on Linux hosts with sysfs **hwmon** access: declarative **`fan_curves.json`** for sensors and PWM curves, optional SMART reads via `smartctl`, a JSON REST API under `/api/v1`, and a dark-themed dashboard at `/`.

The dashboard uses Alpine.js with `fetch()` polling every few seconds (no npm build step).

## Documentation

**Host preparation (kernel modules, sysfs discovery, Docker, capabilities, SMART devices, firewall)** — required reading before deploy:

→ **[docs/HOST_PREREQUISITES.md](docs/HOST_PREREQUISITES.md)**

Includes **Portainer stack deployment** (Git stack, compose path, bind-mount paths).

## Deployment layout

| File | Purpose |
|------|---------|
| [`docker-compose.yml`](docker-compose.yml) | Local **Docker Compose**: builds from [`Dockerfile`](Dockerfile), uses `./config` next to this repo. |
| [`compose.portainer.yml`](compose.portainer.yml) | **Portainer stack**: pulls **`ghcr.io/kecso/fanman`** (no image build on the host). Absolute paths for host config (e.g. `/opt/fanman/config`). |
| [`.github/workflows/publish-image.yml`](.github/workflows/publish-image.yml) | **GitHub Actions**: build and push to **GHCR** on push to `main`, tags `v*`, or manual run. |

The GitHub repo should be **`kecso/fanman`** so the registry path matches **`ghcr.io/kecso/fanman`**. Forks should change the `image:` line in `compose.portainer.yml` if their GHCR namespace differs.

## Quick start (Docker Compose on the host)

After completing [docs/HOST_PREREQUISITES.md](docs/HOST_PREREQUISITES.md):

```bash
cp config/fan_curves.example.json config/fan_curves.json
# Edit sysfs paths under sensors / fans for your board.

docker compose build
docker compose up -d
```

Open `http://localhost:8080`; OpenAPI docs at `/docs`.

Mounts and defaults match `docker-compose.yml` (`CONFIG_PATH=/app/config/fan_curves.json`, `/sys` rw, `/proc` ro).

## Quick start (Portainer)

1. Create the GitHub repo (**`kecso/fanman`**) and push this project. Wait for **Actions** to publish **`ghcr.io/kecso/fanman:latest`** (or tag e.g. **`v1.0.0`** for a semver image).
2. Prepare **`fan_curves.json`** on the Docker host (e.g. under `/opt/fanman/config`).
3. In Portainer: **Stacks → Add stack → Repository**, set compose path **`compose.portainer.yml`**.
4. Adjust **`compose.portainer.yml`** if needed (`volumes`, `devices`, or `image: ghcr.io/kecso/fanman:v1.0.0` instead of `latest`).

If the GHCR package is **private**, configure a **registry** in Portainer or make the package **public** in GitHub **Packages** settings.

Details: [Deploying as a Portainer stack](docs/HOST_PREREQUISITES.md#9-deploying-as-a-portainer-stack).

## Authentication

Not implemented. Use FanMan only on networks you trust (e.g. homelab VLAN). Add TLS or reverse-proxy auth before exposing broadly.

## Configuration file

Disk format is UTF-8 JSON: keys `version`, `global`, `sensors`, `fans`, `smart_devices`. No YAML dependency.

### Full-file rewrite on curve persist

`PUT /api/v1/fans/{name}/curve` replaces **`CONFIG_PATH`** entirely after updating memory: pretty-printed JSON, no partial edits and no preserved comments—plan commentary in Git messages or separate docs.

`POST /api/v1/config/reload` only reads the file from disk.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
CONFIG_PATH=config/fan_curves.example.json SYSFS_PREFIX=/sys PROC_PREFIX=/proc WEB_PORT=8080 \
  python -m uvicorn fanman.main:app --reload --host 127.0.0.1 --port 8080
```

Without valid sysfs paths the process starts but polling logs errors until paths exist.

## Tests

```bash
pytest
```

## Security

FanMan can change cooling behaviour on the host. Do not expose it to untrusted networks without TLS and authentication.
