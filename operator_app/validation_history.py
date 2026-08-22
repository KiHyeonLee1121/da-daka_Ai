"""Persist terminal real-aircraft validation outcomes outside the repository."""

import json
from datetime import datetime, timezone
from pathlib import Path


class ValidationHistory:
    """Append and read deduplicated JSONL validation records."""

    def __init__(self, path: Path) -> None:
        """Store the host-local validation history path."""
        self.path = Path(path)

    def load(self, limit: int = 20) -> list[dict]:
        """Return the most recent valid records without failing on bad lines."""
        if not self.path.exists():
            return []
        records = []
        try:
            lines = self.path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                records.append(item)
        return records[-max(1, int(limit)):]

    def append_terminal(
        self,
        result: str,
        status: dict,
        revision: str,
    ) -> bool:
        """Append one unique SUCCESS or ABORTED terminal result."""
        if not (result.startswith('SUCCESS') or result.startswith('ABORTED')):
            return False
        if any(item.get('result') == result for item in self.load(limit=200)):
            return False
        readiness = status.get('validation_readiness', {})
        record = {
            'recorded_at': datetime.now(timezone.utc).isoformat(),
            'result': result,
            'profile': readiness.get('profile', 'TETHERED_1M_DISTANCE'),
            'revision': revision or 'unknown',
            'battery_percent': status.get('battery_percent'),
            'lidar_m': status.get('lidar_m'),
            'flight_mode': status.get('flight_mode'),
            'landed_state': status.get('landed_state'),
        }
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, separators=(',', ':')) + '\n')
        return True
