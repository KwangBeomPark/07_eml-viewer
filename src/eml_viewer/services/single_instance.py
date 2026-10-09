from __future__ import annotations

import getpass
import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

IPC_SERVER_PREFIX = "App07_EmlViewer_IPC_"
CMD_NEW_WINDOW = "__NEW_WINDOW__"


def get_windows_session_id() -> int | None:
    """현재 프로세스의 Windows 세션 ID를 반환합니다 (RDP / 다중 세션 격리용)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            session_id = wintypes.DWORD()
            if kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(session_id)):
                return session_id.value
        except Exception:
            pass
    return None


def get_default_ipc_server_name() -> str:
    """현재 사용자 및 Windows 세션에 고유한 IPC 서버 이름을 생성합니다."""
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME", "default_user")

    session_id = get_windows_session_id()
    key = f"{user}_sess_{session_id}" if session_id is not None else user
    user_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{IPC_SERVER_PREFIX}{user_hash}"


class SingleInstanceClient:
    """실행 중인 기존 EML Viewer 인스턴스에 명령이나 파일 경로를 전달합니다."""

    @classmethod
    def send_to_primary_instance(
        cls,
        message: str,
        server_name: str | None = None,
        timeout_ms: int = 1500,
        max_retries: int = 2,
    ) -> bool:
        """기존 인스턴스에 메시지를 전송합니다. 전송 및 연결 해제가 온전히 확인되면 True를 반환합니다."""
        target_name = server_name or get_default_ipc_server_name()

        for attempt in range(max_retries + 1):
            socket = QLocalSocket()
            try:
                socket.connectToServer(target_name)
                if not socket.waitForConnected(timeout_ms):
                    socket.abort()
                    if attempt < max_retries:
                        time.sleep(0.05)
                        continue
                    return False

                payload = message.strip().encode("utf-8")
                socket.write(payload)
                socket.flush()

                # 버퍼의 모든 바이트가 기록될 때까지 대기
                if socket.bytesToWrite() > 0:
                    socket.waitForBytesWritten(timeout_ms)

                if socket.bytesToWrite() > 0:
                    logger.warning(
                        "Failed to flush all bytes to primary instance socket (%d remaining)",
                        socket.bytesToWrite(),
                    )
                    socket.abort()
                    if attempt < max_retries:
                        time.sleep(0.05)
                        continue
                    return False

                # 정상 단절 및 서버 수신 완료 대기
                socket.disconnectFromServer()
                socket.waitForDisconnected(timeout_ms)
                if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
                    logger.warning("Socket failed to reach UnconnectedState (current: %s)", socket.state())
                    socket.abort()
                    if attempt < max_retries:
                        time.sleep(0.05)
                        continue
                    return False

                logger.info("Successfully delivered IPC command to primary instance: %s", message)
                return True
            except Exception as exc:
                logger.error("Failed to write to primary instance IPC socket: %s", exc)
                try:
                    socket.abort()
                except Exception:
                    pass
                if attempt < max_retries:
                    time.sleep(0.05)
                    continue
                return False
            finally:
                socket.close()

        return False


class SingleInstanceLock:
    """단일 인스턴스 선출 시 동시 실행 레이스 컨디션을 방지하기 위한 배타적 시스템 락."""

    def __init__(self, lock_name: str | None = None) -> None:
        self._lock_name = lock_name or f"Local\\{get_default_ipc_server_name()}_Lock"
        self._handle = None
        self._fd: int | None = None
        self._is_owner = False

    @property
    def is_owner(self) -> bool:
        return self._is_owner

    def acquire(self) -> bool:
        """배타적 락을 획득합니다. 이미 다른 프로세스가 획득한 경우 False를 반환합니다."""
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.windll.kernel32
                CreateMutexW = kernel32.CreateMutexW
                CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
                CreateMutexW.restype = wintypes.HANDLE
                GetLastError = kernel32.GetLastError
                GetLastError.restype = wintypes.DWORD

                ERROR_ALREADY_EXISTS = 183
                handle = CreateMutexW(None, True, self._lock_name)
                last_error = GetLastError()

                if handle and last_error != ERROR_ALREADY_EXISTS:
                    self._handle = handle
                    self._is_owner = True
                    return True
                else:
                    if handle:
                        kernel32.CloseHandle(handle)
                    self._handle = None
                    self._is_owner = False
                    return False
            except Exception as exc:
                logger.warning("Failed to create exclusive Windows mutex: %s", exc)
                self._is_owner = True
                return True
        else:
            try:
                import fcntl
                import hashlib
                import tempfile

                safe_name = hashlib.sha256(self._lock_name.encode("utf-8")).hexdigest()[:16]
                lock_file = Path(tempfile.gettempdir()) / f".eml_viewer_{safe_name}.lock"
                fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    self._is_owner = True
                    return True
                except (BlockingIOError, OSError):
                    os.close(fd)
                    self._fd = None
                    self._is_owner = False
                    return False
            except Exception as exc:
                logger.warning("Failed to acquire non-Windows lock: %s", exc)
                self._is_owner = False
                return False

    def release(self) -> None:
        if sys.platform == "win32" and self._handle:
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                if self._is_owner:
                    kernel32.ReleaseMutex(self._handle)
                kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        elif sys.platform != "win32" and self._fd is not None:
            try:
                import fcntl

                if self._is_owner:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
        self._is_owner = False


class SingleInstanceServer(QObject):
    """단일 인스턴스 IPC 서버로, 다른 프로세스가 전달한 파일 경로나 새 창 요청을 수신합니다."""

    message_received = Signal(str)

    def __init__(
        self,
        server_name: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server_name = server_name or get_default_ipc_server_name()
        self._lock = SingleInstanceLock(f"Local\\{self._server_name}_Lock")
        self._server: QLocalServer | None = None
        self._is_listening: bool = False
        self._clients: list[QLocalSocket] = []
        self._buffers: dict[QLocalSocket, bytearray] = {}

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    def start(self) -> bool:
        """IPC 서버를 시작합니다. 배타적 락을 먼저 확보한 뒤 파이프를 생성합니다."""
        if not self._lock.acquire():
            logger.warning(
                "Exclusive instance lock for '%s' is held by another process.",
                self._server_name,
            )
            return False

        self._server = QLocalServer(self)

        # 혹시 비정상 종료로 남아있을 수 있는 stale 파이프 정리
        QLocalServer.removeServer(self._server_name)

        if not self._server.listen(self._server_name):
            logger.error(
                "Failed to start QLocalServer on '%s': %s",
                self._server_name,
                self._server.errorString(),
            )
            self._server.deleteLater()
            self._server = None
            self._lock.release()
            return False

        self._is_listening = True
        self._server.newConnection.connect(self._on_new_connection)
        logger.info("SingleInstanceServer listening on '%s'", self._server_name)
        return True

    def stop(self) -> None:
        """IPC 서버를 종료하고 파이프를 제거합니다."""
        for client in list(self._clients):
            try:
                client.readyRead.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                client.disconnected.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                client.close()
                client.deleteLater()
            except RuntimeError:
                pass
        self._clients.clear()
        self._buffers.clear()

        was_listening = self._is_listening
        self._is_listening = False

        if self._server is not None:
            try:
                self._server.newConnection.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._server.close()
            self._server.deleteLater()
            self._server = None

        if was_listening:
            QLocalServer.removeServer(self._server_name)
        self._lock.release()
        logger.info("SingleInstanceServer stopped on '%s'", self._server_name)

    def _on_new_connection(self) -> None:
        if self._server is None:
            return

        client = self._server.nextPendingConnection()
        if client is None:
            return

        client.setParent(self)
        self._clients.append(client)
        self._buffers[client] = bytearray()

        def handle_read() -> None:
            try:
                raw = bytes(client.readAll())
                if raw:
                    self._buffers[client].extend(raw)
            except RuntimeError:
                pass

        def handle_disconnect() -> None:
            try:
                client.readyRead.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                client.disconnected.disconnect()
            except (RuntimeError, TypeError):
                pass

            buf = self._buffers.pop(client, bytearray())
            if client in self._clients:
                self._clients.remove(client)
            try:
                client.deleteLater()
            except RuntimeError:
                pass

            text = buf.decode("utf-8", errors="replace").strip()
            if text:
                logger.info("SingleInstanceServer received command: %s", text)
                self.message_received.emit(text)

        client.readyRead.connect(handle_read)
        client.disconnected.connect(handle_disconnect)

        if client.bytesAvailable() > 0:
            handle_read()
