# Remote — Fleet operations (inventory, WoL, connect, shutdown)

This reference covers the physical-machine side of `/remote`: waking
machines, connecting via SSH/RDP, reboots/shutdowns, and keeping
`infra/remotes/*.yaml` in sync with reality. The service-management side
lives in `workflow.md`.

## Stage 1 — Identify target

1. Parse user request, extract machine name or intent.
2. If machine name: read `infra/remotes/{name}.yaml`.
3. If intent-only ("mein PC"): offer candidates from the inventory.
4. If still ambiguous: list candidates, let the user pick.

## Stage 2 — Fleet overview (on "status" / "check")

Build the status table:

```bash
for f in infra/remotes/*.yaml; do
  [ "$(basename $f)" = "_template.yaml" ] && continue
  name=$(basename "$f" .yaml)
  t=$(grep "^type:" "$f" | awk '{print $2}')
  s=$(grep "^status:" "$f" | awk '{print $2}')
  printf "%-18s %-10s %s\n" "$name" "$t" "$s"
done
```

Then for each machine check reachability (Tailscale IP first, LAN
fallback) via `nc -z -G 2 {ip} 22`.

## Stage 3 — Wake-on-LAN

1. Read `wake_on_lan` block from `infra/remotes/{target}.yaml`.
2. If `enabled: true`, extract `mac` and `method`.
3. If method is `magic-packet via Mac Mini`: run the documented command.
4. **Fallback when `wakeonlan` CLI is missing on the sender:** Python
   one-liner (works everywhere with python3):

   ```bash
   ssh {sender} 'python3 -c "
   import socket
   mac = \"{MAC}\".replace(\":\", \"\")
   magic = bytes.fromhex(\"FF\" * 6 + mac * 16)
   s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
   s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
   s.sendto(magic, (\"192.168.178.255\", 9))
   s.sendto(magic, (\"255.255.255.255\", 9))
   print(\"magic packet sent\")
   "'
   ```

5. Poll reachability for up to 120s (ping or `nc -z` on port 22/3389).
6. Report: "online after Xs" or "timeout — check BIOS WoL, cable, VPN".

## Stage 4 — Connect

1. Prefer Tailscale hostname over LAN IP (works across networks).
2. For SSH: use `ssh {user}@{host}` per yaml `ssh:` block.
3. For RDP on macOS: `open 'rdp://full%20address=s:{host}:3389'`.

## Stage 5 — Shutdown / reboot (destructive — always `[y]` first)

1. **Always** require explicit user confirmation per action.
2. Windows: `ssh {user}@{host} "shutdown /s /t 0"` (stop) or `/r /t 0` (restart).
3. macOS: `ssh {user}@{host} "sudo shutdown -h now"` / `sudo shutdown -r now`.
4. Linux: `ssh {user}@{host} "sudo systemctl poweroff"` / `reboot`.

## Stage 6 — Keep inventory current (with consent)

If during a run you discover drift from `infra/remotes/*.yaml`:
- New IP, new MAC, BIOS update, new service, status change
- Show diff to user, wait for `[y]` before writing the yaml.

## Learned routing patterns

- **"my PC" / "mein PC"** typically maps to a single primary workstation —
  the user's `infra/remotes/*.yaml` sets a `default_target: true` flag on
  the relevant entry. Use that as the implicit target when no explicit
  machine is named.
- **"remote(s)"** in Bridge context = `infra/remotes/*.yaml`, **never**
  `git remote`. On ambiguity ("check my remotes") read `infra/remotes/`
  first, ask only if still unclear.

## Edge cases

- **`wakeonlan` CLI not on homeserver** — Python fallback (Stage 3)
  works reliably. TODO: `brew install wakeonlan` on homeserver or
  update the documented command in `infra/remotes/workstation.yaml` to the
  Python one-liner (needs user consent).
- **workstation boot timing:** after magic packet, ~1-2 min until
  Tailscale/SSH reachable (BIOS POST + Windows boot). Polling timeout
  must be 120s, not 20s.

## Hard rules (repeated from SKILL.md — non-negotiable)

- Read `infra/remotes/{target}.yaml` **before** any operation.
- Tailscale first, LAN as fallback — LAN fails on VPN or foreign networks.
- No destructive operation (shutdown, reboot, format) without per-action `[y]`.
- Never store credentials in `infra/remotes/*.yaml` — KeyVault / 1Password URIs only.
- Honor `wake_on_lan.enabled: false` — never force wake a machine that opted out.
