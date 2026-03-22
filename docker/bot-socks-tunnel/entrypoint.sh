#!/bin/sh
set -eu

if [ -z "${VPS_SSH_HOST:-}" ] || [ -z "${VPS_SSH_USER:-}" ]; then
    echo "Set VPS_SSH_HOST and VPS_SSH_USER (e.g. in .env)"
    exit 1
fi

if [ ! -f /run/ssh-key ]; then
    echo "Mount SSH private key read-only at /run/ssh-key (BOT_SOCKS_SSH_KEY_FILE in .env)"
    exit 1
fi

mkdir -p /root/.ssh
chmod 700 /root/.ssh
install -m 600 /run/ssh-key /tmp/ssh_key

# autossh: перезапуск ssh при обрыве; AUTOSSH_GATETIME=0 — не отключаться после серии сбоев
export AUTOSSH_GATETIME="${AUTOSSH_GATETIME:-0}"
export AUTOSSH_POLL="${AUTOSSH_POLL:-60}"

exec autossh -M 0 -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile=/root/.ssh/known_hosts \
    -p "${VPS_SSH_PORT:-22}" \
    -i /tmp/ssh_key \
    -D 0.0.0.0:1080 \
    "${VPS_SSH_USER}@${VPS_SSH_HOST}"
