# Deploying the DSSG web app cheaply

The app needs a **persistent disk** because uploaded files and generated reports
are stored permanently (under `DSSG_DATA_DIR`, default `/data` in the container).
The cheapest setup that satisfies that is a small VPS running the bundled
Docker Compose stack (app + Caddy for automatic HTTPS).

## Recommended: a ~$4–5/month VPS

Examples: Hetzner CX22 (~€4/mo), DigitalOcean / Vultr / Fly.io small instance.

```bash
# 1. Install Docker + Compose on the box (Debian/Ubuntu):
curl -fsSL https://get.docker.com | sh

# 2. Get the code:
git clone <your-fork-url> vino && cd vino

# 3. Point your domain's A/AAAA record at the server, then:
DOMAIN=dssg.example.com docker compose up -d --build
```

Caddy obtains a Let's Encrypt certificate automatically for `DOMAIN`. The
uploads/reports live in the `dssg-data` Docker volume and survive restarts and
redeploys.

Local test (no domain, plain HTTP on :80):

```bash
docker compose up --build        # then open http://localhost
```

Without Docker (systemd + your own TLS):

```bash
pip install -r requirements.txt
DSSG_DATA_DIR=/var/lib/vino uvicorn dssg.web:app --host 127.0.0.1 --port 8000
# put nginx/Caddy in front for HTTPS
```

## Almost-free: Fly.io with a volume

Container platforms (Fly.io, Render, Railway, Cloud Run) have **ephemeral**
disks, so you must attach persistent storage or uploads will be lost on
redeploy. On Fly.io:

```bash
fly launch --no-deploy                 # generates fly.toml from the Dockerfile
fly volumes create dssg_data --size 1  # 1 GB persistent volume
# add to fly.toml:
#   [mounts]
#     source = "dssg_data"
#     destination = "/data"
fly deploy
```

For stateless platforms (Cloud Run, Render free) you would instead switch
`dssg/store.py` to object storage (S3 / Cloudflare R2, which has a free tier).

## Before going public

- **HTTPS** — handled by Caddy in the compose stack.
- **Disk quota** — uploads are kept forever; size the volume and/or add a cap on
  total stored uploads so the disk can't fill up.
- **Rate limiting** — add a limit at the proxy (e.g. a Caddy rate-limit plugin)
  since uploads are unauthenticated.
- **Backups** — snapshot the `dssg-data` volume if the stored dives matter.
