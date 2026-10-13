#!/bin/sh
set -eu
# This sidecar alone has NET_ADMIN. The app shares its network namespace.
iptables -P OUTPUT DROP
iptables -F OUTPUT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -o lo -d 127.0.0.1 -p tcp --dport 8000 -j ACCEPT
# Docker rewrites the embedded resolver's destination port; restrict by resolver IP.
iptables -A OUTPUT -d 127.0.0.11 -p udp -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p tcp -j ACCEPT
iptables -A OUTPUT -d "$SEARXNG_IP" -p tcp --dport 8080 -j ACCEPT
for cidr in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 \
    172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15 \
    198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4; do
    iptables -A OUTPUT -d "$cidr" -j REJECT
done
iptables -A OUTPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
# IPv6 outbound is disabled at the container layer; the application can use IPv4 fallback.
ip6tables -P OUTPUT DROP
ip6tables -F OUTPUT
ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
touch /tmp/firewall-ready
exec sleep infinity
