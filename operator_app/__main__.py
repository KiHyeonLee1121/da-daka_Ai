"""Launch the Raspberry Pi desktop operator application."""

import os
import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from operator_app.gateway_client import GatewayClient
from operator_app.main_window import OperatorWindow, configure_application
from operator_app.stack_manager import StackManager


def main() -> int:
    """Create the local Qt application and enter its event loop."""
    project_root = Path(
        os.environ.get(
            'DA_DAKA_PROJECT_ROOT',
            Path(__file__).resolve().parents[1],
        )
    ).resolve()
    socket_path = Path(
        os.environ.get(
            'DA_DAKA_OPERATOR_SOCKET',
            project_root / 'ros2_ws' / 'run' / 'operator_gateway.sock',
        )
    )
    compose_file = Path(
        os.environ.get(
            'DA_DAKA_COMPOSE_FILE',
            project_root / 'deploy' / 'pi-compose.yaml',
        )
    )
    app = QApplication(sys.argv)
    configure_application(app)
    window = OperatorWindow(
        project_root,
        GatewayClient(socket_path),
        StackManager(project_root, compose_file),
    )
    window.show()
    return app.exec_()


if __name__ == '__main__':
    raise SystemExit(main())
