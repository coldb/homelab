# Hermes Agent production setup

## Fresh install

Create additional profiles from inside the pod when needed:

```bash
kubectl -n hermes-agent exec deploy/hermes-agent -- hermes profile create <profile-name>
kubectl -n hermes-agent exec deploy/hermes-agent -- hermes -p <profile-name> gateway start
kubectl -n hermes-agent exec deploy/hermes-agent -- hermes -p <profile-name> gateway status
```

Profiles are persisted under `/opt/data/profiles` on the PVC. A container restart restores profiles whose gateway state was `running`.

## Operations

Profile gateway logs persist under `/opt/data/logs/gateways/<profile>/current` on the PVC.
