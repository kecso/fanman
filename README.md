# FanMan

FanMan runs in a single Docker container on Linux hosts with sysfs **hwmon** access: declarative **`fan_curves.json`** for sensors and PWM curves, optional SMART reads via `smartctl`, a JSON REST API under `/api/v1`, and a dark-themed dashboard at `/`.

The dashboard uses Alpine.js with `fetch()` polling every few seconds (no npm build step).

## Documentation

**Host preparation** (kernel modules, sysfs discovery, Docker, capabilities, SMART devices, firewall):

→ **[docs/HOST_PREREQUISITES.md](docs/HOST_PREREQUISITES.md)**

Includes Portainer deployment notes (compose path, bind mounts, registry access).

## Deployment layout

| File | Purpose |
|------|---------|
| [`docker-compose.yml`](docker-compose.yml) | **Docker Compose**: builds from [`Dockerfile`](Dockerfile), bind-mounts `./config`. |
| [`compose.portainer.yml`](compose.portainer.yml) | **Portainer stack**: pulls **`ghcr.io/kecso/fanman`** from GitHub Container Registry (no image build on the host). Absolute paths for host config (see file comments). |
| [`.github/workflows/publish-image.yml`](.github/workflows/publish-image.yml) | **CI**: publishes **`ghcr.io/kecso/fanman`** from this repository (tags include **`latest`** and semver tags when releases are tagged). |

To run a **locally built** image instead, use **`docker-compose.yml`** or replace the **`image:`** line in your stack file.

## Quick start (Docker Compose)

Complete [docs/HOST_PREREQUISITES.md](docs/HOST_PREREQUISITES.md) on the Docker host, then:

```bash
cp config/fan_curves.example.json config/fan_curves.json
# Edit sysfs paths under sensors / fans for your board.

docker compose build
docker compose up -d
```

Open `http://localhost:8080`; API docs at `/docs`.

Mounts match `docker-compose.yml`: `CONFIG_PATH=/app/config/fan_curves.json`, host `/sys` read-write, `/proc` read-only.

## Quick start (Portainer)

Default stack pulls **`ghcr.io/kecso/fanman:latest`** from GHCR.

1. Complete host prerequisites and prepare **`fan_curves.json`** on the Docker machine (bind-mount path is documented in **`compose.portainer.yml`**, commonly **`/opt/fanman/config`** on the host).
2. In Portainer: **Stacks → Add stack**, either:
   - **Repository**: Git URL for this project, compose path **`compose.portainer.yml`**, branch **`main`** (or paste the compose file in the web editor), **or**
   - Paste **`compose.portainer.yml`** and edit **`volumes`** / **`devices`** as needed.
3. Optionally pin a release tag instead of **`latest`**, e.g. **`ghcr.io/kecso/fanman:1.0.0`**.

If **`ghcr.io`** denies the pull (private registry, auth), configure Portainer **Registries** or package visibility—see [docs/HOST_PREREQUISITES.md](docs/HOST_PREREQUISITES.md#9-deploying-as-a-portainer-stack).

## Authentication

Not implemented; intended for trusted networks first. Use TLS and authentication at the proxy if exposing further.

## Configuration file

On-disk format is UTF-8 JSON: **`version`**, **`global`**, **`sensors`**, **`fans`**, **`smart_devices`**.

### Full-file rewrite on curve persist

**`PUT /api/v1/fans/{name}/curve`** persists by rewriting **`CONFIG_PATH`** in full (pretty-printed JSON). Comments are not preserved—keep notes in separate docs if needed.

**`POST /api/v1/config/reload`** reloads from disk without rewriting unless another operation saves.

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
