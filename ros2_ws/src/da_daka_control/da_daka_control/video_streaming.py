"""Pure command construction for Raspberry Pi camera streaming."""

import ipaddress


def build_rpicam_command(
    *,
    executable: str,
    laptop_ip: str,
    port: int,
    width: int,
    height: int,
    framerate: int,
    bitrate_bps: int,
) -> list[str]:
    """Build an argument-only MPEG-TS command without invoking a shell."""
    if not executable:
        raise ValueError('rpicam executable cannot be empty')
    address = ipaddress.ip_address(laptop_ip)
    if not 1 <= port <= 65535:
        raise ValueError('port must be within [1, 65535]')
    if min(width, height, framerate, bitrate_bps) <= 0:
        raise ValueError('video dimensions/rate/bitrate must be positive')
    host = f'[{address}]' if address.version == 6 else str(address)
    output = f'udp://{host}:{port}?pkt_size=1316'
    return [
        executable,
        '-t',
        '0',
        '-n',
        '--codec',
        'libav',
        '--libav-format',
        'mpegts',
        '--low-latency',
        '--width',
        str(width),
        '--height',
        str(height),
        '--framerate',
        str(framerate),
        '--bitrate',
        str(bitrate_bps),
        '-o',
        output,
    ]
