#!/usr/bin/env python3
"""Find likely Raspberry Pi hosts only on directly connected small LANs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import socket
import subprocess


PI_OUIS = {
    'B8:27:EB', 'DC:A6:32', 'E4:5F:01', 'D8:3A:DD',
    '2C:CF:67', '28:CD:C1', '88:A2:9E',
}
PI_NAMES = ('raspberry', 'raspberrypi', 'rpi', 'pi5', 'da-daka', 'da_daka')


def command_json(arguments: list[str]):
    result = subprocess.run(
        arguments, check=True, capture_output=True, text=True, timeout=5
    )
    return json.loads(result.stdout)


def local_networks() -> list[tuple[str, ipaddress.IPv4Network, str]]:
    values = []
    for interface in command_json(['ip', '-j', '-4', 'addr', 'show', 'up']):
        if interface['ifname'] == 'lo' or 'LOOPBACK' in interface.get('flags', []):
            continue
        for address in interface.get('addr_info', []):
            if address.get('scope') != 'global':
                continue
            local = str(address['local'])
            network = ipaddress.ip_network(
                f"{local}/{address['prefixlen']}", strict=False
            )
            values.append((interface['ifname'], network, local))
    return values


def probe(ip: str, timeout: float) -> tuple[bool, bool]:
    ping = subprocess.run(
        ['ping', '-n', '-c', '1', '-W', str(max(1, int(timeout))), ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=timeout + 0.5,
    ).returncode == 0
    ssh = False
    try:
        with socket.create_connection((ip, 22), timeout=min(timeout, 0.4)):
            ssh = True
    except OSError:
        pass
    return ping, ssh


def neighbor_map(interface: str) -> dict[str, str]:
    result = {}
    for item in command_json(['ip', '-j', 'neigh', 'show', 'dev', interface]):
        ip = item.get('dst')
        mac = item.get('lladdr')
        state = set(item.get('state', []))
        if ip and mac and not state.intersection({'FAILED', 'INCOMPLETE'}):
            result[str(ip)] = str(mac).upper()
    return result


def hostname(ip: str) -> str:
    try:
        result = subprocess.run(
            ['getent', 'hosts', ip],
            capture_output=True,
            text=True,
            check=False,
            timeout=0.5,
        )
    except subprocess.TimeoutExpired:
        return ''
    fields = result.stdout.split()
    return fields[1].rstrip('.') if len(fields) > 1 else ''


def classify(mac: str, name: str, ssh: bool) -> tuple[str, str]:
    oui = mac.upper()[:8]
    lowered = name.lower()
    reasons = []
    if oui in PI_OUIS:
        reasons.append('Raspberry Pi MAC prefix')
    if any(token in lowered for token in PI_NAMES):
        reasons.append(f'hostname={name}')
    if ssh:
        reasons.append('SSH port open')
    if any('Raspberry' in reason or 'hostname=' in reason for reason in reasons):
        status = 'RASPBERRY_PI_LIKELY'
    elif ssh:
        status = 'POSSIBLE_PI'
    else:
        status = 'OTHER_HOST'
    return status, ', '.join(reasons) or 'ping/neighbor response only'


def scan(timeout: float) -> list[dict]:
    found = []
    for interface, network, local in local_networks():
        if network.num_addresses > 256:
            print(
                f'SKIP {interface} {network}: /24보다 넓어 자동 탐색하지 않습니다.'
            )
            continue
        targets = [str(ip) for ip in network.hosts() if str(ip) != local]
        with ThreadPoolExecutor(max_workers=min(32, len(targets) or 1)) as pool:
            results = dict(zip(targets, pool.map(lambda ip: probe(ip, timeout), targets)))
        neighbors = neighbor_map(interface)
        for ip in targets:
            ping, ssh = results[ip]
            mac = neighbors.get(ip, '')
            if not ping and not ssh and not mac:
                continue
            name = hostname(ip)
            status, reason = classify(mac, name, ssh)
            found.append({
                'status': status,
                'ip': ip,
                'interface': interface,
                'network': str(network),
                'mac': mac or '-',
                'hostname': name or '-',
                'ping': ping,
                'ssh': ssh,
                'reason': reason,
            })
    rank = {'RASPBERRY_PI_LIKELY': 0, 'POSSIBLE_PI': 1, 'OTHER_HOST': 2}
    return sorted(found, key=lambda item: (rank[item['status']], ipaddress.ip_address(item['ip'])))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='같은 직접 연결 LAN에서 Raspberry Pi 후보 IP를 찾습니다.'
    )
    parser.add_argument('--timeout', type=float, default=1.0)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not 0.2 <= args.timeout <= 5.0:
        parser.error('--timeout must be within 0.2..5.0 seconds')
    try:
        values = scan(args.timeout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f'탐색 실패: {exc}')
        return 1
    if args.json:
        print(json.dumps(values, ensure_ascii=False, indent=2))
        return 0
    likely = [item for item in values if item['status'] == 'RASPBERRY_PI_LIKELY']
    print('\nDA-DAKA 같은 네트워크 Raspberry Pi 탐색 결과')
    print('판정은 MAC/hostname/SSH 단서이며 IP 소유를 100% 보증하지 않습니다.\n')
    for item in values:
        print(
            f"{item['status']:<20} {item['ip']:<15} "
            f"MAC={item['mac']:<17} HOST={item['hostname']:<20} {item['reason']}"
        )
    if not values:
        print('응답한 장치가 없습니다.')
    if likely:
        print('\n가장 유력한 Raspberry Pi IP: ' + ', '.join(item['ip'] for item in likely))
    else:
        print('\n확정적인 Raspberry Pi 후보를 찾지 못했습니다.')
        possible = [item['ip'] for item in values if item['status'] == 'POSSIBLE_PI']
        if possible:
            print('SSH가 열린 확인 필요 후보: ' + ', '.join(possible))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
