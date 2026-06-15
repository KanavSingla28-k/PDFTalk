#!/bin/sh
set -e

# Render alertmanager.yml from template, substituting ADMIN_TOKEN.
# envsubst is available in the prom/alertmanager base image (Alpine).
envsubst '${ADMIN_TOKEN}' \
    < /etc/alertmanager/alertmanager.yml.template \
    > /tmp/alertmanager.yml

exec /bin/alertmanager \
    --config.file=/tmp/alertmanager.yml \
    --storage.path=/alertmanager \
    "$@"
