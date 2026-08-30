# Phase 3B — Tencent Cloud Host Initialization

**Execution date:** 2026-08-28  
**Scope:** host initialization only; no Miru deployment or Phase 4 work.

## Final status

P3B-R0 through P3B-R11: **PASS**

P3B-R12: **PASS**

Production application data, SQLite databases, WeChat databases/keys/media, API keys, and tokens were not uploaded or placed on the host.

## Host and access

- Ubuntu 22.04.5 LTS, x86_64, 2 vCPU, approximately 2 GiB RAM.
- SSH key authentication verified in an independent session.
- Effective SSH settings: public-key authentication enabled; password and keyboard-interactive authentication disabled; root login disabled.
- UFW active with default-deny inbound policy and only TCP/22 allowed (IPv4 and IPv6).
- No listener or external reachability on TCP/80, 443, 8765, or 18080.

## Package and Docker state

- Package manager healthy: no active apt/dpkg transaction, no locks, empty `dpkg --audit`, and `apt-get check` passed.
- Docker CE 29.7.2, Docker CLI 29.7.2, containerd.io 2.3.3, Buildx 0.36.1, and Compose 5.5.0 installed from the official Docker Ubuntu repository.
- Docker and containerd enabled and active.
- Docker daemon logging policy configured in `/etc/docker/daemon.json`:

  ```json
  {
    "log-driver": "json-file",
    "log-opts": {
      "max-size": "20m",
      "max-file": "3"
    }
  }
  ```

- `dockerd --validate` passed; a temporary probe inherited `json-file` with 20m × 3 and was removed.
- `hello-world` was obtained from the Tencent Cloud official internal registry using the verified digest `sha256:5dd0d3e6e255913fc30f90b9f2b1d359cc2cbdb48090cc4b65f1676e203243cc`; `docker run --rm hello-world:latest` printed `Hello from Docker!` and left no container or published port.
- No global registry mirror, daemon proxy, Docker Hub login, or credential was configured or used.

## Resources and persistence

- `/swapfile`: 2 GiB, active and persistent; `vm.swappiness=10`.
- Root filesystem: approximately 50 GiB, 16% used, 40 GiB free; inode use 4%.
- Docker storage below 1 MiB at audit time.
- No failed systemd units after reboot.

## Miru directory boundary

Only these empty directories were created:

| Path | Owner | Mode |
| --- | --- | --- |
| `/opt/miru` | `root:ubuntu` | `0750` |
| `/opt/miru/app` | `ubuntu:ubuntu` | `0750` |
| `/opt/miru/data` | `10001:10001` | `0750` |
| `/opt/miru/backups` | `root:root` | `0700` |
| `/opt/miru/logs` | `ubuntu:ubuntu` | `0750` |

No production configuration, source upload, database, media, WeChat material, secret, or token was created.

## Notes and boundaries

- Docker Hub direct access remained unavailable from this host because registry/auth traffic timed out after the prescribed finite retries. The runtime gate was completed through the authorized Tencent Cloud official internal registry fallback with a pinned digest; no daemon mirror was configured.
- A prior read-only GPG fingerprint check created only `/root/.gnupg/pubring.kbx` and `trustdb.gpg` (empty local audit artifacts, mode 0600); no private key was imported.
- Phase 4 remains explicitly out of scope: no Tailscale, production Caddy, domain/HTTPS, public business ports, Miru deployment, Home Node, WeChat RPC, or endpoint changes.
