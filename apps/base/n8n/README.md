# Updating n8n

Deploy n8n through the [staging overlay](../../staging/n8n/kustomization.yaml) or the [production overlay](../../production/n8n/kustomization.yaml). The shared deployment leaves the tag unset so each overlay controls its own pin.

1. Review and merge the Renovate PR for staging once the image pin includes a digest.
2. Once Flux applies the change in staging, check the n8n rollout and run a representative workflow.
3. In a separate PR, copy the full n8n image entry, including the digest, from the verified staging revision to the production overlay.
