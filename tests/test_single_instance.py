from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication
from eml_viewer.services.single_instance import (
    CMD_NEW_WINDOW,
    SingleInstanceClient,
    SingleInstanceLock,
    SingleInstanceServer,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_single_instance_ipc_e2e(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    server_name = f"Test_IPC_{uuid.uuid4().hex[:8]}"
    server = SingleInstanceServer(server_name=server_name)

    received_messages: list[str] = []
    server.message_received.connect(received_messages.append)

    assert server.start()

    project_root = str(Path(__file__).resolve().parents[1])
    test_file_path = str(tmp_path / "sample.eml")

    # 1. 외부 프로세스에서 파일 경로 전송
    client_script = f"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'''{project_root}''') / 'src'))
from PySide6.QtWidgets import QApplication
from eml_viewer.services.single_instance import SingleInstanceClient
app = QApplication([])
ok = SingleInstanceClient.send_to_primary_instance(r'''{test_file_path}''', '{server_name}')
sys.exit(0 if ok else 1)
"""
    proc = subprocess.Popen([sys.executable, "-c", client_script])

    # 부모 프로세스에서 이벤트 루프를 처리하며 수신 대기
    start_time = time.time()
    while time.time() - start_time < 5.0:
        app.processEvents()
        if len(received_messages) >= 1:
            break
        time.sleep(0.02)

    proc.wait(timeout=5)
    assert proc.returncode == 0
    assert len(received_messages) == 1
    assert received_messages[0] == test_file_path

    # 2. 외부 프로세스에서 CMD_NEW_WINDOW 전송
    client_script_2 = f"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'''{project_root}''') / 'src'))
from PySide6.QtWidgets import QApplication
from eml_viewer.services.single_instance import CMD_NEW_WINDOW, SingleInstanceClient
app = QApplication([])
ok = SingleInstanceClient.send_to_primary_instance(CMD_NEW_WINDOW, '{server_name}')
sys.exit(0 if ok else 1)
"""
    proc2 = subprocess.Popen([sys.executable, "-c", client_script_2])

    start_time = time.time()
    while time.time() - start_time < 5.0:
        app.processEvents()
        if len(received_messages) >= 2:
            break
        time.sleep(0.02)

    proc2.wait(timeout=5)
    assert proc2.returncode == 0
    assert len(received_messages) == 2
    assert received_messages[1] == CMD_NEW_WINDOW

    server.stop()


def test_single_instance_fragmented_delivery():
    app = QApplication.instance() or QApplication([])
    server_name = f"Test_IPC_Frag_{uuid.uuid4().hex[:8]}"
    server = SingleInstanceServer(server_name=server_name)

    received_messages: list[str] = []
    server.message_received.connect(received_messages.append)
    assert server.start()

    # 데이터를 여러 조각으로 나누어 전송하는 별도 클라이언트 프로세스 실행
    frag_script = f"""
import sys
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalSocket

app = QApplication([])
socket = QLocalSocket()
socket.connectToServer('{server_name}')
if not socket.waitForConnected(1000):
    sys.exit(1)

socket.write(b"C:/Mail/")
socket.flush()
time.sleep(0.05)
socket.write(b"important/")
socket.flush()
time.sleep(0.05)
socket.write(b"sample.eml")
socket.flush()
socket.disconnectFromServer()
socket.waitForDisconnected(1000)
sys.exit(0)
"""
    proc = subprocess.Popen([sys.executable, "-c", frag_script])

    start_time = time.time()
    while time.time() - start_time < 3.0:
        app.processEvents()
        if proc.poll() is not None and received_messages:
            break
        time.sleep(0.02)

    proc.wait(timeout=2)
    assert proc.returncode == 0

    # 이벤트 루프를 비워 disconnected 신호 및 버퍼 처리를 완료
    for _ in range(5):
        app.processEvents()
        time.sleep(0.02)

    server.stop()
    for _ in range(5):
        app.processEvents()
        time.sleep(0.01)

    assert len(received_messages) == 1
    assert received_messages[0] == "C:/Mail/important/sample.eml"


def test_single_instance_client_no_server():
    app = QApplication.instance() or QApplication([])
    non_existent = f"NonExistent_{uuid.uuid4().hex[:8]}"
    result = SingleInstanceClient.send_to_primary_instance("test", server_name=non_existent, timeout_ms=200)
    assert not result


def test_single_instance_exclusive_lock_prevents_dual_primary():
    app = QApplication.instance() or QApplication([])
    server_name = f"Test_Lock_{uuid.uuid4().hex[:8]}"
    server1 = SingleInstanceServer(server_name=server_name)
    assert server1.start()

    # 동일한 이름으로 두 번째 서버를 시작하려고 하면 배타적 락에 의해 실패해야 함
    server2 = SingleInstanceServer(server_name=server_name)
    assert not server2.start()

    # 첫 번째 서버가 멈추면 배타적 락이 해제되어 새 서버가 시작 가능해야 함
    server1.stop()
    assert server2.start()
    server2.stop()


def test_single_instance_delayed_server_processing():
    """서버가 클라이언트 전송 시작 시점에 잠시 비동기 지연 상태여도 메시지가 유실되지 않는지 검증합니다."""
    app = QApplication.instance() or QApplication([])
    server_name = f"Test_Delayed_{uuid.uuid4().hex[:8]}"
    server = SingleInstanceServer(server_name=server_name)
    received: list[str] = []
    server.message_received.connect(received.append)
    assert server.start()

    project_root = str(Path(__file__).resolve().parents[1])
    client_script = f"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'''{project_root}''') / 'src'))
from PySide6.QtWidgets import QApplication
from eml_viewer.services.single_instance import SingleInstanceClient
app = QApplication([])
ok = SingleInstanceClient.send_to_primary_instance('DELAYED_CMD', '{server_name}')
sys.exit(0 if ok else 1)
"""
    proc = subprocess.Popen([sys.executable, "-c", client_script])
    # 의도적으로 300ms 동안 부모가 이벤트 처리를 지연
    time.sleep(0.3)

    start = time.time()
    while time.time() - start < 5.0:
        app.processEvents()
        if received:
            break
        time.sleep(0.02)

    proc.wait(timeout=5)
    assert proc.returncode == 0
    server.stop()
    assert received == ["DELAYED_CMD"]


def test_single_instance_lock_posix_flock(monkeypatch):
    """비 Windows 플랫폼에서 fcntl 기반 배타적 락이 올바르게 동작하는지 검증합니다."""
    monkeypatch.setattr(sys, "platform", "linux")
    lock1 = SingleInstanceLock(lock_name="test_posix_lock")
    lock2 = SingleInstanceLock(lock_name="test_posix_lock")

    locks_held = set()

    def mock_flock(fd, operation):
        # 8 = LOCK_UN
        if operation & 8:
            locks_held.discard(fd)
            return
        if locks_held:
            raise BlockingIOError("Resource temporarily unavailable")
        locks_held.add(fd)

    mock_fcntl = MagicMock()
    mock_fcntl.flock = mock_flock
    mock_fcntl.LOCK_EX = 2
    mock_fcntl.LOCK_NB = 4
    mock_fcntl.LOCK_UN = 8

    monkeypatch.setitem(sys.modules, "fcntl", mock_fcntl)

    assert lock1.acquire()
    assert not lock2.acquire()
    lock1.release()
    assert lock2.acquire()
    lock2.release()


def test_single_instance_stop_non_owner_preserves_endpoint():
    """서버 시작에 실패한 secondary 인스턴스가 stop()을 호출해도 primary 엔드포인트를 제거하지 않는지 검증합니다."""
    app = QApplication.instance() or QApplication([])
    server_name = f"Test_NonOwner_{uuid.uuid4().hex[:8]}"
    primary = SingleInstanceServer(server_name=server_name)
    secondary = SingleInstanceServer(server_name=server_name)

    assert primary.start()
    assert not secondary.start()

    with patch("PySide6.QtNetwork.QLocalServer.removeServer") as mock_remove:
        secondary.stop()
        mock_remove.assert_not_called()

    assert primary.is_listening
    primary.stop()
