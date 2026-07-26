#!/usr/bin/env python3
"""
setup_homelab.py

Automates deployment of:
  - A Minecraft Java Edition server (itzg/minecraft-server Docker image)
  - Jellyfin media server (official Jellyfin Docker image)
  - qBittorrent headless client (linuxserver.io Docker image)
  - Tailscale, so all of the above are reachable privately from your other
    devices without opening ports on your router
  - playit.gg agent, to give the Minecraft server a public address you can
    share with people who are NOT on your tailnet (e.g. a cousin)
  - Samba, to share the media/downloads folders over your local network
    file browser (Windows/macOS/Linux)

Target OS: Ubuntu/Debian (uses apt). Run as root or with sudo.

USAGE:
    sudo python3 setup_homelab.py

Before running, review the CONFIG section below and edit paths / memory /
ports to match what you want. This script is idempotent-ish: re-running it
will recreate containers with the same names rather than duplicating them.
"""

import os
import subprocess
import sys
import shutil
import textwrap

# ============================== CONFIG ==================================

MINECRAFT_DATA_DIR = "/opt/minecraft/data"
MINECRAFT_PORT = 25565
MINECRAFT_MEMORY = "4G"          # max JVM heap
MINECRAFT_VERSION = "LATEST"     # or e.g. "1.20.4"
MINECRAFT_TYPE = "VANILLA"       # VANILLA, PAPER, FORGE, FABRIC, etc.
MINECRAFT_EULA_ACCEPTED = False  # you must explicitly accept Mojang's EULA
                                  # https://www.minecraft.net/en-us/eula
                                  # set this to True yourself before running

JELLYFIN_CONFIG_DIR = "/opt/jellyfin/config"
JELLYFIN_CACHE_DIR = "/opt/jellyfin/cache"
JELLYFIN_MEDIA_DIR = "/opt/jellyfin/media"   # point this at your own media
JELLYFIN_PORT = 8096

DOCKER_NETWORK = "homelab"

QBITTORRENT_CONFIG_DIR = "/opt/qbittorrent/config"
QBITTORRENT_DOWNLOADS_DIR = "/opt/qbittorrent/downloads"
QBITTORRENT_WEBUI_PORT = 8080
QBITTORRENT_TORRENT_PORT = 6881

PLAYIT_INSTALL_DIR = "/opt/playit"

SAMBA_ENABLED = True
SAMBA_USER = "homelab"           # Linux + Samba user created for share access
SAMBA_PASSWORD = "CHANGE_ME"     # set this yourself before running the script
SAMBA_WORKGROUP = "WORKGROUP"
# Which directories to share and what to call them on the network
SAMBA_SHARES = {
    "Media": JELLYFIN_MEDIA_DIR,
    "Downloads": QBITTORRENT_DOWNLOADS_DIR,
}

# ==========================================================================


def run(cmd, check=True, capture=False):
    """Run a shell command, streaming output unless capture=True."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def require_root():
    if os.geteuid() != 0:
        sys.exit("This script must be run as root (use sudo). Aborting.")


def command_exists(name):
    return shutil.which(name) is not None


def install_docker():
    if command_exists("docker"):
        print("[ok] Docker already installed.")
        return
    print("[*] Installing Docker...")
    run(["apt-get", "update", "-y"])
    run(["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg"])
    run(["install", "-m", "0755", "-d", "/etc/apt/keyrings"])
    run([
        "bash", "-c",
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg "
        "-o /etc/apt/keyrings/docker.asc"
    ])
    run(["chmod", "a+r", "/etc/apt/keyrings/docker.asc"])
    arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    codename = subprocess.check_output(
        ["bash", "-c", ". /etc/os-release && echo $VERSION_CODENAME"], text=True
    ).strip()
    repo_line = (
        f"deb [arch={arch} signed-by=/etc/apt/keyrings/docker.asc] "
        f"https://download.docker.com/linux/ubuntu {codename} stable\n"
    )
    with open("/etc/apt/sources.list.d/docker.list", "w") as f:
        f.write(repo_line)
    run(["apt-get", "update", "-y"])
    run([
        "apt-get", "install", "-y",
        "docker-ce", "docker-ce-cli", "containerd.io",
        "docker-buildx-plugin", "docker-compose-plugin",
    ])
    print("[ok] Docker installed.")


def ensure_docker_starts_on_boot():
    # Whether Docker was just installed above or was already present,
    # make sure the daemon itself is enabled to start on boot — without
    # this, "--restart unless-stopped" containers won't come back after
    # a reboot because dockerd won't even be running.
    run(["systemctl", "enable", "--now", "docker"])
    print("[ok] Docker daemon enabled to start on boot.")


def install_tailscale():
    if command_exists("tailscale"):
        print("[ok] Tailscale already installed.")
    else:
        print("[*] Installing Tailscale...")
        run(["bash", "-c", "curl -fsSL https://tailscale.com/install.sh | sh"])
        print("[ok] Tailscale installed.")

    # Bring the node up. This requires interactive auth (opens a URL) unless
    # you already have an auth key. If you have one, set TAILSCALE_AUTHKEY
    # in the environment before running this script.
    authkey = os.environ.get("TAILSCALE_AUTHKEY")
    print("[*] Bringing Tailscale up (you may need to open a login URL)...")
    cmd = ["tailscale", "up"]
    if authkey:
        cmd += [f"--authkey={authkey}"]
    run(cmd, check=False)

    status = run(["tailscale", "ip", "-4"], capture=True, check=False)
    ip = status.stdout.strip() if status.returncode == 0 else None
    if ip:
        print(f"[ok] Tailscale is up. This machine's tailnet IP: {ip}")
    else:
        print("[!] Could not confirm Tailscale IP — check `tailscale status` manually.")

    # Make sure the tailscaled service itself is enabled on boot, so the
    # tailnet connection (and therefore reachability of every service
    # below) comes back automatically after a restart.
    run(["systemctl", "enable", "tailscaled"], check=False)
    print("[ok] tailscaled enabled to start on boot.")
    return ip


def ensure_docker_network():
    result = run(["docker", "network", "inspect", DOCKER_NETWORK], check=False, capture=True)
    if result.returncode != 0:
        run(["docker", "network", "create", DOCKER_NETWORK])
        print(f"[ok] Created docker network '{DOCKER_NETWORK}'.")
    else:
        print(f"[ok] Docker network '{DOCKER_NETWORK}' already exists.")


def deploy_minecraft():
    if not MINECRAFT_EULA_ACCEPTED:
        sys.exit(
            "Refusing to start the Minecraft server: you must read "
            "https://www.minecraft.net/en-us/eula and set "
            "MINECRAFT_EULA_ACCEPTED = True in this script yourself."
        )

    os.makedirs(MINECRAFT_DATA_DIR, exist_ok=True)

    print("[*] Deploying Minecraft server container...")
    run(["docker", "rm", "-f", "minecraft"], check=False)
    run([
        "docker", "run", "-d",
        "--name", "minecraft",
        "--restart", "unless-stopped",
        "--network", DOCKER_NETWORK,
        "-p", f"{MINECRAFT_PORT}:25565",
        "-e", "EULA=TRUE",
        "-e", f"MEMORY={MINECRAFT_MEMORY}",
        "-e", f"VERSION={MINECRAFT_VERSION}",
        "-e", f"TYPE={MINECRAFT_TYPE}",
        "-v", f"{MINECRAFT_DATA_DIR}:/data",
        "itzg/minecraft-server:latest",
    ])
    print(f"[ok] Minecraft server starting. World data in {MINECRAFT_DATA_DIR}")
    print(f"     Watch first-boot logs with: docker logs -f minecraft")


def deploy_jellyfin():
    for d in (JELLYFIN_CONFIG_DIR, JELLYFIN_CACHE_DIR, JELLYFIN_MEDIA_DIR):
        os.makedirs(d, exist_ok=True)

    print("[*] Deploying Jellyfin container...")
    run(["docker", "rm", "-f", "jellyfin"], check=False)
    run([
        "docker", "run", "-d",
        "--name", "jellyfin",
        "--restart", "unless-stopped",
        "--network", DOCKER_NETWORK,
        "-p", f"{JELLYFIN_PORT}:8096",
        "-v", f"{JELLYFIN_CONFIG_DIR}:/config",
        "-v", f"{JELLYFIN_CACHE_DIR}:/cache",
        "-v", f"{JELLYFIN_MEDIA_DIR}:/media",
        "jellyfin/jellyfin:latest",
    ])
    print(f"[ok] Jellyfin starting. Media directory: {JELLYFIN_MEDIA_DIR}")
    print("     Add your own legally-owned media there, then finish setup")
    print(f"     in the web UI (first-run wizard) at http://<this-host>:{JELLYFIN_PORT}")


def deploy_qbittorrent():
    """
    Deploys qBittorrent's headless daemon (qbittorrent-nox) via the
    linuxserver.io Docker image, controllable via its Web UI and, since
    it exposes the standard qBittorrent Web API, scriptable from the CLI
    with tools like `curl` or the `qbittorrent-api` Python package.

    NOTE: this only installs the client. Where you point it is up to you.
    Use it for legal content — Linux distro ISOs, material you have
    rights to, files you or your org are legitimately distributing, etc.
    """
    for d in (QBITTORRENT_CONFIG_DIR, QBITTORRENT_DOWNLOADS_DIR):
        os.makedirs(d, exist_ok=True)

    print("[*] Deploying qBittorrent (headless) container...")
    run(["docker", "rm", "-f", "qbittorrent"], check=False)
    run([
        "docker", "run", "-d",
        "--name", "qbittorrent",
        "--restart", "unless-stopped",
        "--network", DOCKER_NETWORK,
        "-e", "PUID=1000",
        "-e", "PGID=1000",
        "-e", "TZ=Etc/UTC",
        "-e", f"WEBUI_PORT={QBITTORRENT_WEBUI_PORT}",
        "-p", f"{QBITTORRENT_WEBUI_PORT}:{QBITTORRENT_WEBUI_PORT}",
        "-p", f"{QBITTORRENT_TORRENT_PORT}:{QBITTORRENT_TORRENT_PORT}",
        "-p", f"{QBITTORRENT_TORRENT_PORT}:{QBITTORRENT_TORRENT_PORT}/udp",
        "-v", f"{QBITTORRENT_CONFIG_DIR}:/config",
        "-v", f"{QBITTORRENT_DOWNLOADS_DIR}:/downloads",
        "lscr.io/linuxserver/qbittorrent:latest",
    ])
    print(f"[ok] qBittorrent starting. Downloads dir: {QBITTORRENT_DOWNLOADS_DIR}")
    print(f"     Web UI: http://<this-host>:{QBITTORRENT_WEBUI_PORT}")
    print("     Default login is printed in the container's first-boot logs:")
    print("     docker logs qbittorrent | grep -i password")
    print("     CLI/scripted control: the Web UI port exposes qBittorrent's")
    print("     HTTP API, usable via `curl` or the `qbittorrent-api` pip package")
    print("     once you've set a login — e.g.:")
    print("       pip install qbittorrent-api")
    print("       python3 -c \"import qbittorrentapi; c=qbittorrentapi.Client("
          "host='localhost', port=8080, username='admin', password='...'); "
          "c.auth_log_in(); print(c.app.version)\"")


def install_playit():
    """
    Installs the playit.gg agent as a systemd service and points it at the
    local Minecraft server port. playit.gg tunnels the server out to a
    public address/port without you forwarding anything on your router —
    useful for a laptop on a home network or behind CGNAT.

    NOTE: the very first run requires a one-time interactive step. The
    agent prints a claim URL that you must open in a browser and log into
    (or create a free account) to link this tunnel. This script cannot
    complete that step for you — it starts the agent and shows you where
    to find that URL.
    """
    os.makedirs(PLAYIT_INSTALL_DIR, exist_ok=True)
    binary_path = os.path.join(PLAYIT_INSTALL_DIR, "playit")

    if not os.path.exists(binary_path):
        print("[*] Downloading playit.gg agent...")
        arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
        arch_map = {"amd64": "amd64", "arm64": "aarch64"}
        playit_arch = arch_map.get(arch, "amd64")
        url = f"https://github.com/playit-cloud/playit-agent/releases/latest/download/playit-linux-{playit_arch}"
        run(["curl", "-fsSL", "-o", binary_path, url])
        run(["chmod", "+x", binary_path])
        print("[ok] playit.gg agent downloaded.")
    else:
        print("[ok] playit.gg agent already downloaded.")

    service_file = "/etc/systemd/system/playit.service"
    if not os.path.exists(service_file):
        unit = textwrap.dedent(f"""\
            [Unit]
            Description=playit.gg tunnel agent
            After=network.target docker.service
            Requires=docker.service

            [Service]
            ExecStart={binary_path}
            WorkingDirectory={PLAYIT_INSTALL_DIR}
            Restart=on-failure
            RestartSec=5
            User=root

            [Install]
            WantedBy=multi-user.target
            """)
        with open(service_file, "w") as f:
            f.write(unit)
        run(["systemctl", "daemon-reload"])

    run(["systemctl", "enable", "playit"], check=False)
    run(["systemctl", "restart", "playit"], check=False)

    print("[ok] playit.gg agent installed and enabled to start on boot.")
    print("[!] FIRST-TIME SETUP REQUIRED:")
    print("    Run:   sudo journalctl -u playit -f")
    print("    Look for a claim URL (https://playit.gg/claim/...), open it in")
    print("    a browser, and log in / sign up to link this agent.")
    print("    After that, go to https://playit.gg -> your agent -> Tunnels ->")
    print(f"    add a Minecraft Java tunnel pointing at localhost:{MINECRAFT_PORT}.")
    print("    playit.gg will then give you a public address like")
    print("    something.joinmc.link:XXXXX — that's what you share with your cousin.")


def setup_samba():
    """
    Installs Samba and shares the configured directories over SMB, so you
    can browse/drag-and-drop files into them from Windows/macOS/Linux
    file managers on your local network without SSHing in.
    """
    if not SAMBA_ENABLED:
        return

    if SAMBA_PASSWORD == "CHANGE_ME":
        sys.exit(
            "Refusing to set up Samba with the default placeholder password. "
            "Edit SAMBA_PASSWORD at the top of this script first."
        )

    print("[*] Installing Samba...")
    run(["apt-get", "install", "-y", "samba"])

    # Create a dedicated Linux user for Samba access if it doesn't exist.
    result = run(["id", "-u", SAMBA_USER], check=False, capture=True)
    if result.returncode != 0:
        run(["useradd", "-M", "-s", "/usr/sbin/nologin", SAMBA_USER])
        print(f"[ok] Created system user '{SAMBA_USER}'.")

    # Set the Samba password for that user (separate from any Linux login).
    proc = subprocess.run(
        ["smbpasswd", "-a", "-s", SAMBA_USER],
        input=f"{SAMBA_PASSWORD}\n{SAMBA_PASSWORD}\n",
        text=True,
    )
    if proc.returncode != 0:
        sys.exit("Failed to set Samba password.")
    run(["smbpasswd", "-e", SAMBA_USER])  # enable the account

    # Make sure the share directories exist and are owned/group-writable.
    for local_name, path in SAMBA_SHARES.items():
        os.makedirs(path, exist_ok=True)
        run(["chgrp", "-R", SAMBA_USER, path], check=False)
        run(["chmod", "-R", "2775", path], check=False)

    smb_conf = "/etc/samba/smb.conf"
    with open(smb_conf, "r") as f:
        existing = f.read()

    marker = "# --- homelab shares (managed by setup_homelab.py) ---"
    if marker not in existing:
        block_lines = [marker, f"workgroup = {SAMBA_WORKGROUP}"]
        for local_name, path in SAMBA_SHARES.items():
            block_lines.append(f"\n[{local_name}]")
            block_lines.append(f"   path = {path}")
            block_lines.append("   browsable = yes")
            block_lines.append("   read only = no")
            block_lines.append("   guest ok = no")
            block_lines.append(f"   valid users = {SAMBA_USER}")
            block_lines.append("   force group = " + SAMBA_USER)
            block_lines.append("   create mask = 0664")
            block_lines.append("   directory mask = 2775")
        with open(smb_conf, "a") as f:
            f.write("\n" + "\n".join(block_lines) + "\n")
        print("[ok] Added share definitions to smb.conf.")
    else:
        print("[ok] smb.conf already has homelab shares configured.")

    run(["systemctl", "enable", "--now", "smbd"])
    run(["systemctl", "enable", "--now", "nmbd"], check=False)
    print("[ok] Samba running and enabled to start on boot.")
    print(f"     Shares: {', '.join(SAMBA_SHARES.keys())}")
    print(f"     Login user: {SAMBA_USER} (password is what you set in SAMBA_PASSWORD)")


def verify_restart_policies():
    """Confirm each container is actually configured to survive a reboot."""
    print("[*] Verifying restart policies...")
    for name in ("minecraft", "jellyfin", "qbittorrent"):
        result = run(
            ["docker", "inspect", "-f", "{{.HostConfig.RestartPolicy.Name}}", name],
            check=False, capture=True,
        )
        policy = result.stdout.strip() if result.returncode == 0 else "MISSING"
        status = "ok" if policy == "unless-stopped" else "!"
        print(f"    [{status}] {name}: restart policy = {policy}")


def print_summary(tailnet_ip):
    host = tailnet_ip or "<tailscale-ip-not-detected>"
    print(textwrap.dedent(f"""
        ================= SETUP COMPLETE =================

        Minecraft server:
            Address (from any device on your tailnet): {host}:{MINECRAFT_PORT}
            World/data dir: {MINECRAFT_DATA_DIR}
            Logs: docker logs -f minecraft

        playit.gg tunnel (for sharing with people NOT on your tailnet, e.g. your cousin):
            One-time setup needed — run: sudo journalctl -u playit -f
            and open the claim URL it prints, then create a Minecraft Java
            tunnel at https://playit.gg pointing to localhost:{MINECRAFT_PORT}.
            The public address playit.gg gives you is what you share.
            Service logs: journalctl -u playit -f

        Samba (local network file sharing):
            From Windows: \\\\{host}\\Media  or  \\\\{host}\\Downloads
            From macOS/Linux: smb://{host}/Media  or  smb://{host}/Downloads
            Login: user '{SAMBA_USER}', password = whatever you set in SAMBA_PASSWORD
            Note: unlike everything else, Samba is on your LOCAL NETWORK,
            not restricted to your tailnet, unless your router/firewall
            already blocks SMB from the internet (most home routers do by default).

        Jellyfin:
            Web UI (from any device on your tailnet): http://{host}:{JELLYFIN_PORT}
            Media dir (put your own legally-owned media here): {JELLYFIN_MEDIA_DIR}
            Logs: docker logs -f jellyfin

        qBittorrent (headless):
            Web UI / API (from any device on your tailnet): http://{host}:{QBITTORRENT_WEBUI_PORT}
            Downloads dir: {QBITTORRENT_DOWNLOADS_DIR}
            Logs: docker logs -f qbittorrent
            Get initial password: docker logs qbittorrent | grep -i password

        Notes:
          - Because both are on your tailnet, you do NOT need to forward
            ports on your home router. Only devices logged into your
            tailnet can reach them.
          - If you want Jellyfin reachable over plain internet with HTTPS
            and no client needed, look into `tailscale serve` /
            `tailscale funnel` (funnel exposes it publicly — be deliberate
            about that).
          - Re-run this script any time to recreate containers with the
            same settings.
          - All three containers (minecraft, jellyfin, qbittorrent) use
            --restart unless-stopped, and both docker and tailscaled are
            enabled as systemd services — so everything comes back
            automatically after a reboot. To test this without actually
            rebooting: `sudo systemctl restart docker` and confirm all
            three containers reappear with `docker ps`.
        ====================================================
    """))


def main():
    require_root()
    install_docker()
    ensure_docker_starts_on_boot()
    tailnet_ip = install_tailscale()
    ensure_docker_network()
    deploy_minecraft()
    deploy_jellyfin()
    deploy_qbittorrent()
    install_playit()
    setup_samba()
    verify_restart_policies()
    print_summary(tailnet_ip)


if __name__ == "__main__":
    main()