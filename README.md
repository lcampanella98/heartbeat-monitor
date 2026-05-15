# heartbeat-monitor

An uptime monitor and status page. See `docs/` for the full product, design, and implementation docs.

## Quick start

```sh
./scripts/start.sh        # real mode (default)
./scripts/start.sh --demo # simulated mode, log email sink
./scripts/stop.sh
./scripts/stop.sh --wipe  # also drops the database volume
```

On Windows:

```powershell
.\scripts\start.ps1
.\scripts\start.ps1 -Demo
.\scripts\stop.ps1
.\scripts\stop.ps1 -Wipe
```
