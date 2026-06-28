# Local App Portal

A small landing page that listens on port 80 and lets other local apps register themselves as clickable links.

## Run

```bash
cd /home/jake/workspace/app-portal
sudo python3 server.py
```

Open `http://localhost/`.

Port 80 requires elevated privileges on this machine. If you do not want to use `sudo`, run a high port instead:

```bash
python3 server.py --port 8080
```

## Install as a Service

```bash
cd /home/jake/workspace/app-portal
./install-service.sh
```

Useful commands:

```bash
systemctl status app-portal.service
journalctl -u app-portal.service -f
sudo systemctl restart app-portal.service
sudo systemctl disable --now app-portal.service
```

## API

Register or update an app:

```http
POST http://localhost/apps
Content-Type: application/json
```

Required JSON:

```json
{
  "name": "My App",
  "port": 3000
}
```

Optional fields:

```json
{
  "id": "my-app",
  "host": "localhost",
  "path": "/",
  "url": "http://localhost:3000/",
  "description": "Short label shown on the portal",
  "tags": ["dev", "dashboard"]
}
```

If `url` is omitted, the portal renders links using whatever host/IP the browser used to open the portal and swaps only the port. For example, opening the portal at `http://10.139.1.74/` renders an app registered on port `5173` as `http://10.139.1.74:5173/`. Explicit `url` values are preserved.

Example:

```bash
curl -X POST http://localhost/apps \
  -H 'Content-Type: application/json' \
  -d '{"name":"My App","port":3000,"description":"Frontend dev server","tags":["react"]}'
```

SDR-Shark registers itself on startup so it is always discoverable here:

```json
{
  "id": "sdr-shark",
  "name": "SDR Shark",
  "port": 3000,
  "description": "Live SDR spectrum and waterfall UI",
  "tags": ["sdr", "spectrum", "waterfall"]
}
```

That registration is intentionally non-fatal. If the portal is down or port 80 is unavailable, SDR-Shark startup continues normally.

SDR-Shark registration knobs:

```bash
SDR_SHARK_REGISTER_WITH_PORTAL=0       # disable registration
SDR_SHARK_PORTAL_URL=http://127.0.0.1/apps
SDR_SHARK_FRONTEND_PORT=3000
SDR_SHARK_PORTAL_NAME="SDR Shark"
SDR_SHARK_PORTAL_ID=sdr-shark
```

Browser example:

```js
await fetch("http://localhost/apps", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name: "My App", port: 3000 })
});
```

List registered apps:

```bash
curl http://localhost/api/apps
```

Remove an app:

```bash
curl -X DELETE http://localhost/api/apps/my-app-3000
```
