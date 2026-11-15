#!/bin/sh
# Firewall микросервисов. Работает в сетевом пространстве хоста и управляет цепочкой DOCKER-USER,
# через которую ядро пропускает весь трафик между контейнерами (в том числе внутри одного bridge
# благодаря br_netfilter). Порядок: established -> белый список -> DROP всего внутреннего трафика.
set -eu
CHAIN=DOCKER-USER
INTERNAL=172.30.0.0/16
RULES=/fw/rules.conf

addr_args() {
  case "$2" in
    *-*) echo "-m iprange --$1-range $2" ;;
    *)   echo "-$(echo "$1" | cut -c1) $2" ;;
  esac
}

rule_args() {
  port_args="-p tcp"
  [ "$4" != "all" ] && port_args="-p tcp --dport $4"
  echo "$(addr_args src "$2") $(addr_args dst "$3") $port_args -m comment --comment $1"
}

apply() {
  iptables -F $CHAIN
  iptables -A $CHAIN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  grep -v '^#' $RULES | grep -v '^$' | while read -r name src dst port; do
    iptables -A $CHAIN $(rule_args "$name" "$src" "$dst" "$port") -j ACCEPT
  done
  iptables -A $CHAIN -s $INTERNAL -d $INTERNAL -m comment --comment default-deny -j DROP
  iptables -A $CHAIN -j RETURN
  echo "firewall applied"
}

deny() {
  line=$(grep -E "^$1[[:space:]]" $RULES) || { echo "no rule $1"; exit 1; }
  set -- $line
  iptables -D $CHAIN $(rule_args "$1" "$2" "$3" "$4") -j ACCEPT
  iptables -I $CHAIN 1 $(rule_args "deny-$1" "$2" "$3" "$4") -j DROP  # выше ESTABLISHED: рвёт и уже открытые соединения
  echo "rule $1 removed, flow $2 -> $3:$4 blocked"
}

case "${1:-show}" in
  apply) apply ;;
  deny)  deny "$2" ;;
  off)   iptables -F $CHAIN && iptables -A $CHAIN -j RETURN && echo "firewall disabled" ;;
  show)  iptables -L $CHAIN -n -v --line-numbers ;;
  *)     echo "usage: fw.sh apply|show|deny <rule>|off"; exit 1 ;;
esac
