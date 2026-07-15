"""
성림 라이브 제어기 - 웹 서버 (FastAPI + WebSocket)
브라우저에서 카메라 스트리밍 및 PTZ 제어를 위한 백엔드 서버입니다.

실행 방법:
    python web_server.py

접속 방법:
    로컬:  http://localhost:8000
    LAN:   http://<이 PC의 IP>:8000
    외부:  공유기에서 8000번 포트 포워딩 후 http://<공인IP>:8000
"""

import asyncio
import base64
import json
import threading
import time
import os
from contextlib import asynccontextmanager

import cv2
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ─────────────────── 카메라 설정 ───────────────────
CAMERA_CONFIGS = {
    1: {
        "name": "예배당 좌측 (1번)",
        "srt_main": "srt://mev.o-r.kr:20001",
        "rtsp_main": "rtsp://mev.o-r.kr:20001/stream1",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 20004,
    },
    2: {
        "name": "예배당 중앙 (2번)",
        "srt_main": "srt://mev.o-r.kr:20002",
        "rtsp_main": "rtsp://mev.o-r.kr:20002/stream1",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 20005,
    },
    3: {
        "name": "예배당 우측 (3번)",
        "srt_main": "srt://mev.o-r.kr:20003",
        "rtsp_main": "rtsp://mev.o-r.kr:20003/stream1",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 20006,
    },
}

INTERNAL_CONFIGS = {
    1: {"srt_main": "srt://192.168.0.91", "rtsp_main": "rtsp://192.168.0.91:554/stream1", "ctrl_ip": "192.168.0.91", "ctrl_port": 80},
    2: {"srt_main": "srt://192.168.0.92", "rtsp_main": "rtsp://192.168.0.92:554/stream1", "ctrl_ip": "192.168.0.92", "ctrl_port": 80},
    3: {"srt_main": "srt://192.168.0.90", "rtsp_main": "rtsp://192.168.0.90:554/stream1", "ctrl_ip": "192.168.0.90", "ctrl_port": 80},
}

# ─────────────────── 스트림 관리 ───────────────────

class StreamManager:
    """
    RTSP/SRT 캡처를 백그라운드 스레드에서 유지하고,
    연결된 모든 WebSocket에 JPEG 프레임을 브로드캐스트합니다.
    """

    def __init__(self):
        self.current_camera_id = 3
        self.network_mode = "external"
        self._cap = None
        self._lock = threading.Lock()
        self._frame = None  # 최신 JPEG 바이트
        self._status = "초기화 중..."
        self._running = False
        self._thread = None
        self._subscribers: list[asyncio.Queue] = []
        self._loop = None  # 메인 이벤트 루프 참조 (브로드캐스트용)

    def start(self, camera_id: int):
        """스트림 전환 (기존 스레드 종료 후 새로 시작)"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        self.current_camera_id = camera_id
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _get_urls(self):
        cam_id = self.current_camera_id
        if self.network_mode == "internal":
            cfg = INTERNAL_CONFIGS[cam_id]
        else:
            cfg = CAMERA_CONFIGS[cam_id]
        return cfg["srt_main"], cfg["rtsp_main"]

    def _get_ctrl(self):
        cam_id = self.current_camera_id
        if self.network_mode == "internal":
            cfg = INTERNAL_CONFIGS[cam_id]
        else:
            cfg = CAMERA_CONFIGS[cam_id]
        return cfg["ctrl_ip"], cfg["ctrl_port"]

    def _capture_loop(self):
        is_connected = False
        cap = None

        while self._running:
            if not is_connected:
                srt_url, rtsp_url = self._get_urls()

                # SRT 시도
                self._set_status("SRT 연결 중...")
                cap = cv2.VideoCapture(srt_url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        is_connected = True
                        self._set_status("SRT 연결 완료")
                        self._push_frame(frame)

                # RTSP 폴백
                if not is_connected:
                    if cap:
                        cap.release()
                    self._set_status("RTSP 연결 중...")
                    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                    if cap.isOpened():
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            is_connected = True
                            self._set_status("RTSP 연결 완료")
                            self._push_frame(frame)

                if not is_connected:
                    if cap:
                        cap.release()
                        cap = None
                    self._set_status("연결 실패 (재시도 대기)")
                    time.sleep(3)
                    continue

            # 메인 캡처 루프
            try:
                ret, frame = cap.read()
                if ret and frame is not None:
                    self._push_frame(frame)
                else:
                    is_connected = False
                    if cap:
                        cap.release()
                        cap = None
                    self._set_status("스트림 끊김 (재연결 시도)")
                    time.sleep(1)
            except Exception:
                is_connected = False
                if cap:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                self._set_status("스트림 오류 (재연결 시도)")
                time.sleep(1)

        if cap:
            try:
                cap.release()
            except Exception:
                pass

    def _set_status(self, msg: str):
        self._status = msg
        # 상태 변경을 구독자에게 알림
        self._broadcast_status(msg)

    def _push_frame(self, frame):
        """프레임을 JPEG로 인코딩 후 모든 구독자에게 전달"""
        # 해상도 축소 (전송 대역폭 최적화): 1280×720 이하로
        h, w = frame.shape[:2]
        if w > 1280:
            scale = 1280 / w
            frame = cv2.resize(frame, (1280, int(h * scale)), interpolation=cv2.INTER_AREA)

        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            return

        jpeg_bytes = buf.tobytes()
        b64 = base64.b64encode(jpeg_bytes).decode("ascii")
        msg = json.dumps({"type": "frame", "data": b64})
        self._broadcast(msg)

    def _broadcast(self, msg: str):
        if self._loop is None:
            return
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, msg)
            except Exception:
                pass

    def _broadcast_status(self, status: str):
        msg = json.dumps({"type": "status", "status": status, "camera_id": self.current_camera_id})
        self._broadcast(msg)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    @property
    def status(self):
        return self._status


stream_manager = StreamManager()

# ─────────────────── FastAPI 앱 ───────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    stream_manager._loop = asyncio.get_event_loop()
    stream_manager.start(stream_manager.current_camera_id)
    yield


app = FastAPI(title="성림 라이브 제어기 웹", lifespan=lifespan)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/cameras")
async def get_cameras():
    """카메라 목록 및 현재 상태 반환"""
    result = {}
    for cam_id, cfg in CAMERA_CONFIGS.items():
        result[cam_id] = {"name": cfg["name"], "id": cam_id}
    return JSONResponse({
        "cameras": result,
        "current_camera_id": stream_manager.current_camera_id,
        "network_mode": stream_manager.network_mode,
        "status": stream_manager.status,
    })


@app.post("/api/switch_camera/{camera_id}")
async def switch_camera(camera_id: int):
    """카메라 전환"""
    if camera_id not in CAMERA_CONFIGS:
        return JSONResponse({"error": "Invalid camera ID"}, status_code=400)
    stream_manager.start(camera_id)
    return JSONResponse({"ok": True, "camera_id": camera_id})


@app.post("/api/network_mode/{mode}")
async def set_network_mode(mode: str):
    """네트워크 모드 전환 (external / internal)"""
    if mode not in ("external", "internal"):
        return JSONResponse({"error": "Invalid mode"}, status_code=400)
    stream_manager.network_mode = mode
    stream_manager.start(stream_manager.current_camera_id)
    return JSONResponse({"ok": True, "mode": mode})


@app.post("/api/ptz/{camera_id}/{command}")
async def ptz_command(camera_id: int, command: str, speed1: int = 10, speed2: int = 10):
    """PTZ 제어 명령 프록시"""
    if camera_id not in CAMERA_CONFIGS:
        return JSONResponse({"error": "Invalid camera ID"}, status_code=400)

    if stream_manager.network_mode == "internal":
        cfg = INTERNAL_CONFIGS[camera_id]
    else:
        cfg = CAMERA_CONFIGS[camera_id]

    ip = cfg["ctrl_ip"]
    port = cfg["ctrl_port"]
    base_url = f"http://{ip}:{port}/cgi-bin/ptzctrl.cgi"

    # 명령 URL 구성
    if command == "stop":
        url = f"{base_url}?ptzcmd&ptzstop&0&0"
    elif command == "zoomstop":
        url = f"{base_url}?ptzcmd&zoomstop&5"
    elif command in ("zoomin", "zoomout"):
        url = f"{base_url}?ptzcmd&{command}&{speed1}"
    elif command == "preset":
        url = f"{base_url}?ptzcmd&poscall&{speed1}"
    elif command in ("up", "down", "left", "right"):
        url = f"{base_url}?ptzcmd&{command}&{speed1}&{speed2}"
    else:
        return JSONResponse({"error": "Unknown command"}, status_code=400)

    def do_request():
        try:
            resp = requests.get(url, auth=HTTPBasicAuth("admin", "admin"), timeout=5)
            return resp.status_code == 200
        except RequestException:
            return False

    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, do_request)
    return JSONResponse({"ok": ok, "url": url})


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """카메라 영상 프레임을 WebSocket으로 스트리밍"""
    await websocket.accept()
    q = stream_manager.subscribe()

    # 현재 상태 즉시 전송
    await websocket.send_text(json.dumps({
        "type": "status",
        "status": stream_manager.status,
        "camera_id": stream_manager.current_camera_id,
    }))

    try:
        while True:
            msg = await asyncio.wait_for(q.get(), timeout=10.0)
            await websocket.send_text(msg)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        stream_manager.unsubscribe(q)
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────── 진입점 ───────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  성림 라이브 제어기 - 웹 서버")
    print("=" * 55)
    print("  로컬 접속:  http://localhost:8000")
    print("  LAN  접속:  http://<이 PC의 IP>:8000")
    print("  외부 접속:  공유기 포트포워딩 후 http://<공인IP>:8000")
    print("  종료:       Ctrl+C")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
