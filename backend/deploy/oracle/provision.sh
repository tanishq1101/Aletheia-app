#!/usr/bin/env bash
#
# Prepare a fresh Oracle Cloud A1 instance to run the Aletheia API.
# Run it ON the instance, once:
#
#     curl -fsSLO <this file>   # or scp it up
#     sudo bash provision.sh
#
# Idempotent -- safe to re-run after a failure or an OS upgrade.
#
# ############################################################################
# WHAT THIS SCRIPT CANNOT DO
#
# An Oracle instance sits behind TWO independent firewalls. This script opens
# the one *on* the instance. The other is the VCN security list (or network
# security group) in the Oracle console, and it is not reachable from inside
# the instance at all.
#
# If you skip that second one, everything here will report success, `docker
# compose ps` will show both containers healthy, Caddy will sit waiting for an
# ACME challenge that never arrives, and the service will be unreachable with
# no error anywhere that explains why. It is the single most common way this
# deployment fails. The script prints the exact steps at the end.
# ############################################################################

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	echo "provision.sh must run as root: sudo bash provision.sh" >&2
	exit 1
fi

APP_DIR=/opt/aletheia
# The unprivileged login user, so it can run docker without sudo afterwards.
# Oracle's images use 'ubuntu' or 'opc' depending on the image chosen.
TARGET_USER="${SUDO_USER:-}"

log() { printf '\n==> %s\n' "$*"; }

# --- which distro -----------------------------------------------------------
# Oracle's A1 images are Oracle Linux (the console default) or Ubuntu. They
# differ in package manager and, more importantly, in firewall: Oracle Linux
# runs firewalld, Ubuntu ships raw iptables rules with a REJECT at the end of
# the INPUT chain.
. /etc/os-release
log "detected ${PRETTY_NAME:-unknown} on $(uname -m)"

case "$(uname -m)" in
	aarch64) ;;
	*) echo "WARNING: this is not aarch64. An A1 instance is Ampere; if you are on
         an x86 shape the image still builds, but you are not on the always-free
         A1 shape you think you are." >&2 ;;
esac

# --- docker -----------------------------------------------------------------
install_docker_debian() {
	log "installing Docker from Docker's apt repository"
	apt-get update -qq
	apt-get install -y -qq ca-certificates curl gnupg
	install -m 0755 -d /etc/apt/keyrings
	if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
		curl -fsSL "https://download.docker.com/linux/${ID}/gpg" \
			| gpg --dearmor -o /etc/apt/keyrings/docker.gpg
		chmod a+r /etc/apt/keyrings/docker.gpg
	fi
	cat > /etc/apt/sources.list.d/docker.list <<-EOF
		deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable
	EOF
	apt-get update -qq
	apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

install_docker_rhel() {
	log "installing Docker from Docker's yum repository"
	dnf install -y -q dnf-plugins-core
	# Oracle Linux tracks CentOS Stream closely enough that Docker's centos
	# repository is the one that resolves; there is no separate OL repo.
	dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true
	# Oracle Linux ships podman's docker shim, which owns the same file paths.
	dnf remove -y -q podman-docker runc 2>/dev/null || true
	dnf install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
	log "docker and the compose plugin are already installed"
else
	case "${ID}" in
		ubuntu | debian) install_docker_debian ;;
		ol | oracle | rhel | centos | almalinux | rocky) install_docker_rhel ;;
		*)
			echo "Unsupported distro '${ID}'. Install Docker Engine and the compose
plugin by hand, then re-run this script -- it will skip straight past this step." >&2
			exit 1
			;;
	esac
fi

systemctl enable --now docker

if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
	usermod -aG docker "$TARGET_USER"
	log "added '$TARGET_USER' to the docker group (log out and back in for it to apply)"
fi

# --- the firewall ON the instance -------------------------------------------
# Caddy needs 80 as well as 443: 80 is where the Let's Encrypt HTTP-01 challenge
# arrives, so closing it does not "only" lose the HTTP redirect, it prevents the
# certificate from ever being issued.
open_ports_iptables() {
	log "opening 80/443 in iptables"
	for port in 80 443; do
		# -C tests for the rule, so re-running does not stack duplicates.
		iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
			|| iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
	done
	iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null \
		|| iptables -I INPUT 1 -p udp --dport 443 -j ACCEPT

	# Persist, or the rules vanish on the next reboot and the service comes back
	# unreachable for reasons that look unrelated to a reboot.
	if command -v netfilter-persistent >/dev/null 2>&1; then
		netfilter-persistent save
	else
		DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent
		netfilter-persistent save
	fi
}

open_ports_firewalld() {
	log "opening 80/443 in firewalld"
	firewall-cmd --permanent --add-service=http  >/dev/null
	firewall-cmd --permanent --add-service=https >/dev/null
	firewall-cmd --permanent --add-port=443/udp  >/dev/null
	firewall-cmd --reload >/dev/null
}

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
	log "opening 80/443 in ufw"
	ufw allow 80/tcp >/dev/null
	ufw allow 443/tcp >/dev/null
	ufw allow 443/udp >/dev/null
elif systemctl is-active --quiet firewalld 2>/dev/null; then
	open_ports_firewalld
else
	open_ports_iptables
fi

# --- where the deployment lives ---------------------------------------------
log "creating $APP_DIR"
mkdir -p "$APP_DIR"
if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
	chown -R "$TARGET_USER":"$TARGET_USER" "$APP_DIR"
fi

# --- the part a script cannot do --------------------------------------------
PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo '<look it up in the console>')"

cat <<EOF

============================================================================
The instance is ready. Two things remain, and NEITHER can be done from here.

1. OPEN THE VCN SECURITY LIST -- the second firewall.

   Oracle console -> Networking -> Virtual Cloud Networks -> your VCN ->
   Subnets -> your subnet -> Security Lists -> Default Security List ->
   Add Ingress Rules. Add two:

     Source 0.0.0.0/0   IP Protocol TCP   Destination Port Range 80
     Source 0.0.0.0/0   IP Protocol TCP   Destination Port Range 443

   Skip this and everything will look healthy and be unreachable.

2. POINT DNS AT THIS INSTANCE.

   This instance's public IP: ${PUBLIC_IP}

   Create an A record for the hostname you will put in API_DOMAIN pointing at
   that IP, and wait for it to resolve before deploying -- Caddy asks Let's
   Encrypt for a certificate on startup, and a failed challenge is rate
   limited. Check from your laptop, not from here:

     dig +short your-name.duckdns.org

Then, from your laptop, in the repo:

     ./backend/deploy/oracle/deploy.sh ${TARGET_USER:-ubuntu}@${PUBLIC_IP}
============================================================================

EOF
