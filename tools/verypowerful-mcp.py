#!/usr/bin/env python3
"""
verypowerful — MCP server for the sovereign relay stack.

One tool surface for the whole edge: Cloudflare DNS admin, the VPS L4/SNI
relay, and the node's Caddy vhosts + container inventory. Pure stdlib, stdio
JSON-RPC (MCP 2024-11-05).

Topology assumptions (the VeryPowerful pattern):
  - workstation (here) has ssh aliases `node` and `vps`
  - the Cloudflare account token is IP-allowlisted to NODE's egress, so every
    CF API call is executed on node via ssh, forced IPv4
  - ls-route (in ~/libresynergy-stack) owns SNI-map + Caddy vhost automation

Register:  claude mcp add --scope user verypowerful -- python3 /home/yaya/verypowerful/mcp-server.py
"""
import json, os, re, shlex, subprocess, sys

REPO = os.path.expanduser("~/libresynergy-stack")
CF_ENV = os.path.join(REPO, "secrets", "cloudflare.env")
NODE, VPS = "node", "vps"
NODE_CADDYFILE = "/home/yaya/docker/Caddyfile"
_zone_cache = {}

def sh(cmd, timeout=60):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def cf_token():
    for line in open(CF_ENV):
        if line.startswith("CF_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("no CF_API_TOKEN in secrets/cloudflare.env")

def cf(method, path, body=None):
    """Cloudflare API call, executed on node (token is IP-locked to node)."""
    tok = cf_token()
    cmd = ["curl", "-4", "-s", "-X", method,
           "-H", f"Authorization: Bearer {tok}",
           "-H", "Content-Type: application/json",
           f"https://api.cloudflare.com/client/v4{path}"]
    if body is not None:
        cmd += ["--data", json.dumps(body)]
    rc, out, err = sh(["ssh", NODE, " ".join(shlex.quote(c) for c in cmd)], timeout=45)
    if rc != 0:
        raise RuntimeError(f"ssh/curl failed: {err or out}")
    d = json.loads(out)
    if not d.get("success"):
        raise RuntimeError(f"cloudflare: {d.get('errors')}")
    return d["result"]

def zone_id(zone):
    if zone not in _zone_cache:
        res = cf("GET", f"/zones?name={zone}")
        if not res:
            raise RuntimeError(f"zone {zone} not in this account")
        _zone_cache[zone] = res[0]["id"]
    return _zone_cache[zone]

# ---------------- tool implementations ----------------------------------------
def t_dns_list(zone):
    res = cf("GET", f"/zones/{zone_id(zone)}/dns_records?per_page=100")
    return [{"name": r["name"], "type": r["type"], "content": r["content"],
             "proxied": r.get("proxied", False), "id": r["id"]} for r in res]

def t_dns_upsert(zone, name, type="A", content=None, proxied=False, ttl=300):
    if not content:
        raise RuntimeError("content required")
    fqdn = name if name.endswith(zone) else (f"{name}.{zone}" if name else zone)
    existing = cf("GET", f"/zones/{zone_id(zone)}/dns_records?type={type}&name={fqdn}")
    body = {"type": type, "name": fqdn, "content": content, "ttl": ttl, "proxied": proxied}
    if existing:
        r = cf("PUT", f"/zones/{zone_id(zone)}/dns_records/{existing[0]['id']}", body)
        return {"action": "updated", "record": f"{type} {fqdn} -> {content}"}
    cf("POST", f"/zones/{zone_id(zone)}/dns_records", body)
    return {"action": "created", "record": f"{type} {fqdn} -> {content}"}

def t_dns_delete(zone, name, type="A"):
    fqdn = name if name.endswith(zone) else f"{name}.{zone}"
    existing = cf("GET", f"/zones/{zone_id(zone)}/dns_records?type={type}&name={fqdn}")
    if not existing:
        return {"action": "noop", "reason": "record not found"}
    cf("DELETE", f"/zones/{zone_id(zone)}/dns_records/{existing[0]['id']}")
    return {"action": "deleted", "record": f"{type} {fqdn}"}

def t_route_web(sub, port):
    rc, out, err = sh([f"{REPO}/bin/ls-route", "web", str(sub), str(port)], timeout=120)
    if rc != 0:
        raise RuntimeError(f"ls-route failed: {err or out}")
    return {"ok": True, "output": out}

def t_route_tcp(name, port):
    rc, out, err = sh([f"{REPO}/bin/ls-route", "tcp", str(name), str(port)], timeout=120)
    if rc != 0:
        raise RuntimeError(f"ls-route failed: {err or out}")
    return {"ok": True, "output": out}

def t_routes_list():
    rc, sni, _ = sh(["ssh", VPS, "grep -v '^#' /etc/nginx/stream-sni-map.conf"], timeout=30)
    rc2, tcp, _ = sh(["ssh", VPS, "for f in /etc/nginx/stream.d/*.conf; do echo \"== $f\"; cat $f; done 2>/dev/null"], timeout=30)
    return {"sni_map": sni.splitlines(), "tcp_forwards": tcp.splitlines()}

def t_containers():
    rc, out, err = sh(["ssh", NODE, "docker ps --format '{{.Names}}\\t{{.Status}}\\t{{.Ports}}'"], timeout=30)
    if rc != 0:
        raise RuntimeError(err or out)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        rows.append({"name": parts[0], "status": parts[1] if len(parts) > 1 else "",
                     "ports": parts[2] if len(parts) > 2 else ""})
    return rows

def t_caddy_vhosts():
    rc, out, err = sh(["ssh", NODE, f"cat {NODE_CADDYFILE}"], timeout=30)
    if rc != 0:
        raise RuntimeError(err or out)
    vhosts = []
    cur = None
    for line in out.splitlines():
        m = re.match(r"^([a-z0-9.,\s-]+\.[a-z]{2,}[a-z0-9.,\s-]*)\s*\{\s*$", line)
        if m:
            cur = {"hosts": [h.strip() for h in m.group(1).split(",")], "backends": []}
            vhosts.append(cur)
        elif cur is not None:
            b = re.search(r"reverse_proxy\s+(?:[/\S]+\s+)?(\S+:\d+)", line)
            if b: cur["backends"].append(b.group(1))
            if re.search(r"root \* (\S+)", line):
                cur["backends"].append("static:" + re.search(r"root \* (\S+)", line).group(1))
    return vhosts

def t_caddy_reload():
    rc, out, err = sh(["ssh", NODE, "docker restart yaya-caddy-1"], timeout=60)
    if rc != 0:
        raise RuntimeError(err or out)
    return {"ok": True, "restarted": out}

def t_dns_sync():
    rc, out, err = sh(f"scp -q {REPO}/scripts/cf-dns-sync.sh {NODE}:/tmp/cfsync.sh && "
                      f"scp -q {CF_ENV} {NODE}:/tmp/cfsync.env && "
                      f"ssh {NODE} 'mkdir -p /tmp/cfsync.d/secrets /tmp/cfsync.d/scripts && "
                      f"mv /tmp/cfsync.sh /tmp/cfsync.d/scripts/ && mv /tmp/cfsync.env /tmp/cfsync.d/secrets/cloudflare.env'",
                      timeout=60)
    # ship a minimal env for the script
    rc, envout, _ = sh(f"grep -E '^LS_BASE_DOMAIN|^LS_RELAY_PUBLIC_IP' {REPO}/libresynergy.env", timeout=10)
    sh(["ssh", NODE, f"printf '%s\\nLS_SECRETS_DIR=/tmp/cfsync.d/secrets\\n' {shlex.quote(envout)} > /tmp/cfsync.d/libresynergy.env"], timeout=15)
    rc, out, err = sh(["ssh", NODE, "bash /tmp/cfsync.d/scripts/cf-dns-sync.sh; rm -rf /tmp/cfsync.d"], timeout=180)
    return {"exit": rc, "output": (out + "\n" + err).strip()}

TOOLS = {
    "dns_list": (t_dns_list, "List all DNS records in a Cloudflare zone.",
        {"zone": {"type": "string", "description": "zone name, e.g. yaya.sh or libresynergy.org"}}, ["zone"]),
    "dns_upsert": (t_dns_upsert, "Create or update a DNS record (DNS-only by default — TLS terminates on the node).",
        {"zone": {"type": "string"}, "name": {"type": "string", "description": "subdomain or fqdn; empty = apex"},
         "type": {"type": "string", "default": "A"}, "content": {"type": "string", "description": "e.g. the relay IP"},
         "proxied": {"type": "boolean", "default": False}, "ttl": {"type": "integer", "default": 300}}, ["zone", "name", "content"]),
    "dns_delete": (t_dns_delete, "Delete a DNS record.",
        {"zone": {"type": "string"}, "name": {"type": "string"}, "type": {"type": "string", "default": "A"}}, ["zone", "name"]),
    "route_web": (t_route_web, "Publish an HTTPS service: adds relay SNI-map entry + node Caddy vhost (idempotent).",
        {"sub": {"type": "string", "description": "subdomain of the base domain"},
         "port": {"type": "integer", "description": "node loopback port"}}, ["sub", "port"]),
    "route_tcp": (t_route_tcp, "Publish a raw-TCP service: opens relay firewall + nginx stream forward (games, RTMP, db).",
        {"name": {"type": "string"}, "port": {"type": "integer"}}, ["name", "port"]),
    "routes_list": (t_routes_list, "Show the relay's current SNI (web) routes and raw-TCP forwards.", {}, []),
    "containers": (t_containers, "Inventory of containers running on the node with status and published ports.", {}, []),
    "caddy_vhosts": (t_caddy_vhosts, "Parse the node Caddyfile: every vhost and the backend(s) it proxies to.", {}, []),
    "caddy_reload": (t_caddy_reload, "Restart the node's Caddy (picks up Caddyfile changes; ~2s of edge downtime).", {}, []),
    "dns_sync": (t_dns_sync, "Run the full cf-dns-sync: ensure every LibreSynergy host record exists in the base zone.", {}, []),
}

# ---------------- MCP stdio loop -----------------------------------------------
def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = {"code": -32000, "message": str(error)}
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
        if method == "initialize":
            reply(mid, {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "verypowerful", "version": "1.0.0"}})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            tools = []
            for name, (_, desc, props, required) in TOOLS.items():
                tools.append({"name": name, "description": desc,
                              "inputSchema": {"type": "object", "properties": props,
                                              "required": required}})
            reply(mid, {"tools": tools})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in TOOLS:
                reply(mid, error=f"unknown tool {name}")
                continue
            try:
                result = TOOLS[name][0](**args)
                reply(mid, {"content": [{"type": "text", "text": json.dumps(result, indent=1)}]})
            except Exception as e:
                reply(mid, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        elif mid is not None:
            reply(mid, error=f"method {method} not supported")

if __name__ == "__main__":
    main()
