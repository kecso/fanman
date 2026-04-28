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
| [`compose.portainer.yml`](compose.portainer.yml) | **Portainer stack**: pulls a **GHCR image** (no build on the host). Uses absolute paths for host config (see file comments). |
| [`.github/workflows/publish-image.yml`](.github/workflows/publish-image.yml) | **CI**: builds and pushes **`ghcr.io/<owner>/<repo>`** on pushes to `main`, tags matching `v*`, or manual workflow runs. |

Pre-built images follow the GitHub repository name (lowercase). **`compose.portainer.yml`** ships with an **`image:`** line pointing at this project’s registry path; **forks** should change it to match their GHCR namespace (or build locally via `docker-compose.yml`).

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

1. Ensure a container image is available—typically from CI (**GHCR**) or built locally and pushed to your registry.
2. Place **`fan_curves.json`** on the host (see **`compose.portainer.yml`** for the expected bind-mount path, often something like `/opt/fanman/config`).
3. In Portainer: **Stacks → Add stack →** point at this repository **or** paste **`compose.portainer.yml`**, with compose path **`compose.portainer.yml`** when using Git.
4. Adjust **`volumes`**, **`devices`**, and **`image:`** (e.g. pin **`ghcr.io/owner/repo:1.0.0`** instead of **`latest`**) for your environment.

Private GHCR packages require registry credentials in Portainer or a public package visibility setting—see [docs/HOST_PREREQUISITES.md](docs/HOST_PREREQUISITES.md#9-deploying-as-a-portainer-stack).

## Authentication

Not implemented; intended for trusted networks first. Use TLS and authentication at the proxy if exposing further.

## Configuration file

On-disk format is UTF-8 JSON: **`version`**, **`global`**, **`sensors`**, **`fans`**, **`smart_devices`**.

### Full-file rewrite on curve persist

**`PUT /api/v1/fans/{name}/curve`** persists by rewriting **`CONFIG_PATH`** in full (pretty-printed JSON). Comments are not preserved—keep notes in Git or separate docs.

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
