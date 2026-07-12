import sys
import cv2
import os
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from camera_controller import CameraController
from logger_setup import logger

CAMERA_CONFIGS = {
    1: {
        "name": "예배당 좌측 (1번)",
        "srt_main": "srt://mev.o-r.kr:20001",
        "rtsp_main": "rtsp://mev.o-r.kr:20001/stream1",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 8001
    },
    2: {
        "name": "예배당 중앙 (2번)",
        "srt_main": "srt://mev.o-r.kr:20002",
        "rtsp_main": "rtsp://mev.o-r.kr:20002/stream1",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 8002
    },
    3: {
        "name": "예배당 우측 (3번)",
        "srt_main": "srt://mev.o-r.kr:20003",
        "rtsp_main": "rtsp://mev.o-r.kr:20003/stream1",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 8003
    }
}

class VideoThread(QThread):
    """
    RTSP/SRT 영상 스트림 수신 및 화면 방출용 스레드 (분석 없이 순수 캡처만 수행)
    """
    change_pixmap_signal = pyqtSignal(QImage)
    status_signal = pyqtSignal(str)

    def __init__(self, camera_id, srt_url, rtsp_url):
        super().__init__()
        self.camera_id = camera_id
        self.srt_url = srt_url
        self.rtsp_url = rtsp_url
        self._run_flag = True
        self._cap = None
        self.is_connected = False
        self.active_protocol = "None"

    def run(self):
        while self._run_flag:
            if not self.is_connected:
                # 1. SRT 우선 연결 시도
                self.status_signal.emit("SRT 연결 시도 중...")
                self._cap = cv2.VideoCapture(self.srt_url, cv2.CAP_FFMPEG)
                if self._cap.isOpened():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        self.is_connected = True
                        self.active_protocol = "SRT"
                        self.status_signal.emit("SRT 연결 성공")
                        self.emit_frame(frame)
                
                # 2. SRT 실패 시 RTSP 폴백 시도
                if not self.is_connected:
                    if self._cap:
                        self._cap.release()
                    self.status_signal.emit("RTSP 연결 시도 중...")
                    self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                    if self._cap.isOpened():
                        ret, frame = self._cap.read()
                        if ret and frame is not None:
                            self.is_connected = True
                            self.active_protocol = "RTSP"
                            self.status_signal.emit("RTSP 연결 성공")
                            self.emit_frame(frame)
                
                if not self.is_connected:
                    self.status_signal.emit("연결 실패 (대기 후 재시도)")
                    self.msleep(3000)
                    continue

            # 연결된 상태에서의 반복 프레임 캡처
            ret, frame = self._cap.read()
            if ret and frame is not None:
                self.emit_frame(frame)
            else:
                self.is_connected = False
                if self._cap:
                    self._cap.release()
                self.status_signal.emit("스트림 유실됨 (재연결 중)")
                self.msleep(1000)

        if self._cap:
            self._cap.release()

    def emit_frame(self, frame):
        try:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = rgb_image.strides[0]
            qt_image = QImage(rgb_image.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.change_pixmap_signal.emit(qt_image.copy())
        except Exception as e:
            logger.error(f"프레임 변환 및 방출 에러: {e}")

    def stop(self):
        self._run_flag = False
        self.wait()


class LiteControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.current_camera_id = 3
        self.preset_buffer = ""
        self.video_thread = None
        
        self.init_ui()
        self.start_stream(self.current_camera_id)

    def init_ui(self):
        self.setWindowTitle("성림 카메라 초경량 라이브 컨트롤러")
        self.setGeometry(150, 150, 960, 620)
        self.setStyleSheet("background-color: #121418;")
        
        # 메인 레이아웃 (복잡한 UI/로그창/버튼 모두 걷어내고 오직 비디오와 상태 라벨만 배치)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 1. 상태 및 입력 정보 표시용 라벨 (포커스를 뺏지 않는 단순 텍스트)
        self.status_label = QLabel("상태 로딩 중...")
        self.status_label.setStyleSheet("color: #58d68d; font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(self.status_label)
        
        # 2. 비디오 출력 영역
        self.video_label = QLabel("영상 스트림 연결 중...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #08090b; border: 1px solid #2c303b; border-radius: 6px; color: #7f8c8d; font-size: 16px; font-weight: bold;")
        self.video_label.setMinimumSize(800, 480)
        layout.addWidget(self.video_label)
        
        # 키보드 이벤트 작동의 핵심인 포커스 설정
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()

    def start_stream(self, camera_id):
        if self.video_thread is not None:
            self.video_thread.stop()
            self.video_thread = None
            
        config = CAMERA_CONFIGS[camera_id]
        self.current_camera_id = camera_id
        
        self.video_thread = VideoThread(camera_id, config["srt_main"], config["rtsp_main"])
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.status_signal.connect(self.update_status_msg)
        self.video_thread.start()
        
        # 카메라 하드웨어 제어 컨트롤러 초기화
        self._init_camera_ctrl()
        self.update_status_display()

    def update_image(self, img):
        pix = QPixmap.fromImage(img).scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.video_label.setPixmap(pix)

    def update_status_msg(self, msg):
        self.update_status_display(extra=msg)

    def update_status_display(self, extra=""):
        config = CAMERA_CONFIGS[self.current_camera_id]
        status_txt = f"[{config['name']}]"
        if extra:
            status_txt += f" - {extra}"
        if self.preset_buffer:
            status_txt += f" | 입력 중인 프리셋: {self.preset_buffer}"
        else:
            status_txt += " | 입력 중인 프리셋: 없음 (숫자 입력 후 Spacebar)"
        self.status_label.setText(status_txt)

    def _init_camera_ctrl(self):
        config = CAMERA_CONFIGS[self.current_camera_id]
        try:
            self.camera = CameraController(config["ctrl_ip"], "admin", "admin", port=config["ctrl_port"])
            logger.info(f"카메라 {self.current_camera_id}번 PTZ 제어 연동 완료 ({config['ctrl_ip']}:{config['ctrl_port']})")
        except Exception as e:
            logger.error(f"카메라 제어 연동 실패: {e}")

    def move_to_preset(self):
        if not self.preset_buffer:
            return
        preset_num = int(self.preset_buffer)
        logger.info(f"카메라 {self.current_camera_id}번 프리셋 {preset_num}번 이동 실행")
        if self.camera:
            self.camera.move_to_preset(preset_num)
        self.preset_buffer = ""
        self.update_status_display()

    def start_move(self, direction):
        if self.camera:
            self.camera.move_continuous(direction, 10, 10)

    def stop_move(self, cmd="move"):
        if self.camera:
            self.camera.stop_movement(cmd)

    def keyPressEvent(self, event: QKeyEvent):
        if event.isAutoRepeat(): return
        key = event.key()
        text = event.text().lower()

        # 1. F1, F2, F3: 카메라 즉시 전환
        if key == Qt.Key.Key_F1:
            self.start_stream(1)
        elif key == Qt.Key.Key_F2:
            self.start_stream(2)
        elif key == Qt.Key.Key_F3:
            self.start_stream(3)

        # 2. WASD: 상/좌/하/우 조작 (한/영 모드 대응)
        elif key == Qt.Key.Key_W or text == 'ㅈ':
            self.start_move("up")
        elif key == Qt.Key.Key_S or text == 'ㄴ':
            self.start_move("down")
        elif key == Qt.Key.Key_A or text == 'ㅁ':
            self.start_move("left")
        elif key == Qt.Key.Key_D or text == 'ㅇ':
            self.start_move("right")
            
        # 3. QE: 줌 제어 (한/영 모드 대응)
        elif key == Qt.Key.Key_Q or text == 'ㅂ':
            self.start_move("zoomin")
        elif key == Qt.Key.Key_E or text == 'ㄷ':
            self.start_move("zoomout")

        # 4. 0 ~ 9: 프리셋 번호 키 입력
        elif (Qt.Key.Key_0 <= key <= Qt.Key.Key_9) or (Qt.Key.Key_Keypad0 <= key <= Qt.Key.Key_Keypad9):
            num_char = text if text.isdigit() else str(key - Qt.Key.Key_0)
            if Qt.Key.Key_Keypad0 <= key <= Qt.Key.Key_Keypad9:
                num_char = str(key - Qt.Key.Key_Keypad0)
            self.preset_buffer += num_char
            self.update_status_display()

        # 5. Spacebar: 프리셋 이동 확정 실행
        elif key == Qt.Key.Key_Space:
            self.move_to_preset()

        # 6. Backspace, Escape
        elif key == Qt.Key.Key_Backspace:
            self.preset_buffer = self.preset_buffer[:-1]
            self.update_status_display()
        elif key == Qt.Key.Key_Escape:
            self.preset_buffer = ""
            self.update_status_display()

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.isAutoRepeat(): return
        key = event.key()
        text = event.text().lower()
        
        if key in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D] or text in ['ㅈ','ㄴ','ㅁ','ㅇ']:
            self.stop_move("move")
        elif key in [Qt.Key.Key_Q, Qt.Key.Key_E] or text in ['ㅂ','ㄷ']:
            self.stop_move("zoom")

    def closeEvent(self, event):
        if self.video_thread is not None:
            self.video_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LiteControlGUI()
    window.show()
    sys.exit(app.exec())
