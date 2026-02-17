# Systemd Units for SigPro JSONL Phase-1

These units run:
- `signal-inbound-collector.service` (continuous JSONL -> SQLite collector)
- `sigpro-consumer.timer` + `sigpro-consumer.service` (periodic SigPro consumer)

Hardened variants are also included:
- `signal-inbound-collector-hardened.service`
- `sigpro-consumer-hardened.service`
- `sigpro-consumer-hardened.timer`

## Install

```bash
mkdir -p ~/.config/systemd/user
cp /home/james/.openclaw/workspace-sigpro/deploy/systemd/*.service ~/.config/systemd/user/
cp /home/james/.openclaw/workspace-sigpro/deploy/systemd/*.timer ~/.config/systemd/user/

systemctl --user daemon-reload

# Standard profile
systemctl --user enable --now signal-inbound-collector.service
systemctl --user enable --now sigpro-consumer.timer

# Hardened profile (preferred)
# cp /home/james/.openclaw/workspace-sigpro/deploy/systemd/sigpro.env.example \
#    /home/james/.openclaw/workspace-sigpro/deploy/systemd/sigpro.env
# systemctl --user enable --now signal-inbound-collector-hardened.service
# systemctl --user enable --now sigpro-consumer-hardened.timer
```

## Check status

```bash
systemctl --user status signal-inbound-collector.service
systemctl --user status sigpro-consumer.timer
systemctl --user list-timers | grep sigpro-consumer
```

## Logs

```bash
journalctl --user -u signal-inbound-collector.service -f
journalctl --user -u sigpro-consumer.service -f
```

## Stop

```bash
systemctl --user disable --now sigpro-consumer.timer
systemctl --user disable --now signal-inbound-collector.service
```

## Notes

- Collector singleton lock file: `.openclaw/signal_inbound.lock`
- Raw ingress JSONL: `.openclaw/signal_inbound_raw.jsonl`
- Event DB: `.openclaw/signal_events.db`
