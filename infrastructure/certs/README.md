# TLS certificates

`compose.prod.yaml` mounts this directory read-only at `/etc/nginx/certs`; nginx
expects exactly two files:

| File | Purpose |
|---|---|
| `tls.crt` | PEM certificate chain (server certificate first) |
| `tls.key` | PEM private key |

The files are **not committed**: `.gitignore` excludes everything in this
directory except this README and `.gitkeep`.

## Real deployment

Install the certificate and key issued for the public host name (for example
with Let's Encrypt/certbot or the organisation's PKI), then rebuild nothing:
only the mount is read. Keep the key readable by root and mounted read-only.
Restart the `frontend` service after replacing the files:

```bash
docker compose --env-file .env.production \
  -f compose.yaml -f compose.prod.yaml restart frontend
```

Set `PUBLIC_ORIGIN` to the matching `https://<host>` value so the CSRF origin
check accepts the browser origin.

## Local deployment verification

A self-signed certificate is enough to verify TLS, Secure cookies and the proxy
on this machine. It is **not** a production certificate. Generate one with the
bundled script (Docker supplies OpenSSL, so no host dependency is needed):

```powershell
# Windows PowerShell
.\infrastructure\scripts\generate-self-signed-cert.ps1
```

```bash
# Linux / macOS
./infrastructure/scripts/generate-self-signed-cert.sh
```

The certificate covers `DNS:localhost` and `IP:127.0.0.1` for 365 days. Use
`https://localhost` for the application (the certificate is self-signed, so the
browser shows a warning; the Playwright verification sets
`E2E_IGNORE_HTTPS_ERRORS=true`). Do not use HSTS-trusting browser profiles for
development on the same host: the nginx configuration deliberately omits HSTS
for `localhost` and `127.0.0.1`.
