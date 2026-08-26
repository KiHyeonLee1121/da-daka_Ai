from pathlib import Path
import subprocess


REPOSITORY = Path(__file__).resolve().parents[2]


def test_observe_launcher_uses_camera_only_mode():
    monitor = (REPOSITORY / 'tools/start_live_ai_monitor.sh').read_text()
    camera = (REPOSITORY / 'tools/gpu_laptop_start_pi_camera.sh').read_text()

    assert 'DA_DAKA_CAMERA_ONLY=1' in monitor
    assert 'DA_DAKA_NONINTERACTIVE=1' in monitor
    assert 'if [[ "${DA_DAKA_CAMERA_ONLY}" == "1" ]]' in camera
    assert 'exec rpicam-vid' in camera
    assert 'edge_gpu_link.py' in camera


def test_desktop_templates_are_portable_and_parseable():
    templates = list((REPOSITORY / 'desktop').glob('*.desktop.in'))

    assert len(templates) == 2
    for template in templates:
        contents = template.read_text()
        assert contents.startswith('[Desktop Entry]\n')
        assert 'Type=Application' in contents
        assert '/home/jeedaeng' not in contents


def test_gpu_laptop_shell_launchers_have_valid_syntax():
    scripts = [
        'tools/gpu_laptop_start_pi_camera.sh',
        'tools/start_live_ai_monitor.sh',
        'tools/start_live_ai_monitor_desktop.sh',
        'tools/find_raspberry_pi_desktop.sh',
        'tools/install_gpu_laptop_desktop_apps.sh',
    ]

    for relative in scripts:
        subprocess.run(
            ['bash', '-n', str(REPOSITORY / relative)],
            check=True,
        )
