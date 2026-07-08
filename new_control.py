import sys
import cv2
import threading
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDialog, QFrame
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent, QPainter, QPen, QColor, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from camera_controller import CameraController

# 카메라 설정 정보
CAMERA_CONFIGS = {
    1: {
        "name": "예배당 좌측 (1번)",
        "srt_main": "srt://mev.o-r.kr:20001",
        "rtsp_main": "rtsp://mev.o-r.kr:20001/stream1",
        "ctrl_ip": "192.168.0.88",
        "ctrl_port": 80
    },
    2: {
        "name": "예배당 중앙 (2번)",
        "srt_main": "srt://mev.o-r.kr:20002",
        "rtsp_main": "rtsp://mev.o-r.kr:20002/stream1",
        "ctrl_ip": "192.168.0.89",
        "ctrl_port": 80
    },
    3: {
        "name": "예배당 우측 (3번)",
        "srt_main": "srt://mev.o-r.kr:20003",
        "rtsp_main": "rtsp://mev.o-r.kr:20003/stream1",
        "ctrl_ip": "192.168.0.90",
        "ctrl_port": 80
    }
}

class VideoThread(QThread):
    """
    영상 스트림을 비동기로 수신하여 GUI로 전달하는 독립 스레드
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
                # 1. SRT 연결 시도
                self.status_signal.emit("SRT 연결 중...")
                self._cap = cv2.VideoCapture(self.srt_url, cv2.CAP_FFMPEG)
                if self._cap.isOpened():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        self.is_connected = True
                        self.active_protocol = "SRT"
                        self.status_signal.emit("SRT 연결 완료")
                        self.emit_frame(frame)
                
                # 2. SRT 실패 시 RTSP 폴백
                if not self.is_connected:
                    if self._cap:
                        self._cap.release()
                    self.status_signal.emit("RTSP 연결 중...")
                    self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                    if self._cap.isOpened():
                        ret, frame = self._cap.read()
                        if ret and frame is not None:
                            self.is_connected = True
                            self.active_protocol = "RTSP"
                            self.status_signal.emit("RTSP 연결 완료")
                            self.emit_frame(frame)

                if not self.is_connected:
                    self.status_signal.emit("연결 실패 (재시도 대기)")
                    self.msleep(3000)
                    continue

            # 영상 캡처 루프
            ret, frame = self._cap.read()
            if ret and frame is not None:
                self.emit_frame(frame)
            else:
                self.is_connected = False
                if self._cap:
                    self._cap.release()
                self.status_signal.emit("스트림 끊김 (재연결 시도)")
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
        except Exception:
            pass

    def stop(self):
        self._run_flag = False
        self.wait()


class OverlayVideoLabel(QLabel):
    """
    비디오 화면 위에 십자(Crosshair)와 9분할 그리드 오버레이를 그리는 커스텀 QLabel.
    show_overlay 속성으로 켜고 끌 수 있음 (기본: ON).
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.show_overlay = True

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.show_overlay:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # ── 9분할 그리드선 (흰색 반투명) ──
        grid_pen = QPen(QColor(255, 255, 255, 70))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        painter.drawLine(w // 3, 0, w // 3, h)
        painter.drawLine(2 * w // 3, 0, 2 * w // 3, h)
        painter.drawLine(0, h // 3, w, h // 3)
        painter.drawLine(0, 2 * h // 3, w, 2 * h // 3)

        # ── 십자 표시 (중앙, 청록색) ──
        cx, cy = w // 2, h // 2
        arm = 14
        gap = 4

        cross_pen = QPen(QColor(0, 255, 200, 220))
        cross_pen.setWidth(1)
        painter.setPen(cross_pen)
        # 가로선 (중앙 gap 제외)
        painter.drawLine(cx - arm, cy, cx - gap, cy)
        painter.drawLine(cx + gap, cy, cx + arm, cy)
        # 세로선 (중앙 gap 제외)
        painter.drawLine(cx, cy - arm, cx, cy - gap)
        painter.drawLine(cx, cy + gap, cx, cy + arm)
        # 중앙 작은 원 (지름 4px)
        painter.drawEllipse(cx - 2, cy - 2, 4, 4)

        painter.end()


class HelpModal(QDialog):
    """
    단축키 안내 모달 다이얼로그.
    아무 키 입력이나 클릭 시 자동으로 닫힘.
    """
    SHORTCUTS = [
        ("F1 / F2 / F3",        "카메라 1번 / 2번 / 3번 전환"),
        ("W / A / S / D",        "카메라 상 / 좌 / 하 / 우 이동"),
        ("Q / E",                "줌 인 / 줌 아웃"),
        ("Z",                    "팬틸트 속도 조정 모드 토글"),
        ("X",                    "줌 속도 조정 모드 토글"),
        ("+  /  −",              "속도 증가 / 감소  (Z: 1~24 팬틸트 / X: 1~9 줌)"),
        ("숫자  +  Space",       "프리셋 번호 입력 후 이동"),
        ("ESC",                  "프리셋 입력 버퍼 초기화"),
        ("Backspace",            "계산기 수식 한 글자 삭제"),
        ("텐키  숫자 / 연산자",  "계산기 수식 입력"),
        ("텐키  Enter",          "계산기 수식 계산"),
        ("H",                    "십자 / 9분할 오버레이 토글  (기본: ON)"),
        ("Shift  +  ?",          "이 단축키 안내창 열기"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self._build_ui()
        if parent:
            self.setGeometry(parent.geometry())

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 반투명 전체 배경
        backdrop = QWidget()
        backdrop.setStyleSheet("background-color: rgba(8, 10, 14, 190); border-radius: 0px;")
        backdrop_layout = QVBoxLayout(backdrop)
        backdrop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 중앙 패널
        panel = QWidget()
        panel.setFixedWidth(600)
        panel.setStyleSheet(
            "background-color: #161920;"
            "border: 1px solid #2a3a50;"
            "border-radius: 14px;"
        )
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(32, 28, 32, 28)
        panel_layout.setSpacing(0)

        # 제목
        title = QLabel("⌨️   단축키 안내")
        title.setStyleSheet(
            "color: #00ffd2; font-size: 17px; font-weight: bold;"
            "font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;"
            "border: none; background: transparent; padding-bottom: 10px;"
        )
        panel_layout.addWidget(title)

        # 구분선
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #2a3a50; border: none;")
        panel_layout.addWidget(divider)
        panel_layout.addSpacing(10)

        # 단축키 행 목록
        for key, desc in self.SHORTCUTS:
            row = QWidget()
            row.setStyleSheet("background: transparent; border: none;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 4, 0, 4)
            row_layout.setSpacing(0)

            key_label = QLabel(key)
            key_label.setFixedWidth(195)
            key_label.setStyleSheet(
                "color: #7fb3d3; font-family: 'Consolas', 'Segoe UI', sans-serif;"
                "font-size: 13px; font-weight: bold;"
                "background: transparent; border: none;"
            )

            sep_label = QLabel("—")
            sep_label.setFixedWidth(24)
            sep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sep_label.setStyleSheet(
                "color: #2a3a50; font-size: 13px;"
                "background: transparent; border: none;"
            )

            desc_label = QLabel(desc)
            desc_label.setStyleSheet(
                "color: #a8b8c8; font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;"
                "font-size: 13px; background: transparent; border: none;"
            )

            row_layout.addWidget(key_label)
            row_layout.addWidget(sep_label)
            row_layout.addWidget(desc_label, 1)
            panel_layout.addWidget(row)

        panel_layout.addSpacing(14)

        # 하단 닫기 힌트
        close_hint = QLabel("아무 키나 누르거나 클릭하면 닫힙니다")
        close_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        close_hint.setStyleSheet(
            "color: #3d4f61; font-size: 11px; font-style: italic;"
            "background: transparent; border: none;"
        )
        panel_layout.addWidget(close_hint)

        backdrop_layout.addWidget(panel)
        outer.addWidget(backdrop)

    def keyPressEvent(self, event):
        self.accept()

    def mousePressEvent(self, event):
        self.accept()


class NewControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.current_camera_id = 3
        self.preset_buffer = ""
        self.last_preset = "없음"
        self.current_status = "대기 중"
        self.calc_buffer = ""
        self.calc_result = ""
        self.video_thread = None
        self.show_overlay = True  # 오버레이(십자/9분할) 표시 여부 (기본: ON)
        
        # 속도 설정 상태
        self.pan_tilt_speed = 10  # 팬틸트 속도 (1~24)
        self.zoom_speed = 3       # 줌 속도 (1~9)
        self.speed_mode = None    # None | 'pan_tilt' | 'zoom'
        
        self.init_ui()
        self.start_stream(self.current_camera_id)

    def init_ui(self):
        self.setWindowTitle("성림 라이브 제어기 (안정화 버전)")
        self.setWindowIcon(QIcon("icon.ico"))
        self.setGeometry(150, 150, 960, 620)
        self.setStyleSheet("background-color: #121418;")
        
        # 메인 위젯 및 수직 레이아웃 (어떤 포커스 뺏는 위젯도 존재하지 않음)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 1. 상단 정보 영역을 위한 가로 레이아웃 (패널들을 가로로 나열)
        top_container = QWidget()
        top_layout = QHBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)  # 두 패널 사이 간격
        
        # 좌측 상태 정보 패널 (모던 메탈 다크 테마)
        status_panel = QWidget()
        status_panel.setStyleSheet("background-color: #161920; border: 1px solid #232d3f; border-radius: 8px;")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(15, 12, 15, 12)
        self.status_label = QLabel("로딩 중...")
        self.status_label.setStyleSheet("color: #ecf0f1; font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; font-size: 13px; border: none; background: transparent;")
        status_layout.addWidget(self.status_label)
        
        # 우측 계산기 패널 (전문 LCD 디스플레이 느낌)
        calc_panel = QWidget()
        calc_panel.setStyleSheet("background-color: #0c0e12; border: 1px solid #1e2530; border-radius: 8px;")
        calc_layout = QVBoxLayout(calc_panel)
        calc_layout.setContentsMargins(15, 12, 15, 12)
        self.calc_label = QLabel("🔢 계산기: 대기 중")
        self.calc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.calc_label.setStyleSheet("color: #00ffd2; font-family: 'Consolas', 'Segoe UI', sans-serif; font-size: 14px; font-weight: bold; border: none; background: transparent;")
        calc_layout.addWidget(self.calc_label)
        
        # 가로 비율 배치: 상태 패널 65%, 계산기 패널 35%
        top_layout.addWidget(status_panel, stretch=65)
        top_layout.addWidget(calc_panel, stretch=35)
        layout.addWidget(top_container)
        
        # 2. 비디오 화면 라벨 (오버레이 커스텀 QLabel 사용)
        self.video_label = OverlayVideoLabel("비디오 스트림 로딩 중...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #08090b; border: 1px solid #1a202c; border-radius: 8px; color: #7f8c8d; font-size: 15px; font-weight: bold;")
        self.video_label.setMinimumSize(800, 480)
        layout.addWidget(self.video_label)

        # 하단 힌트 텍스트 (단축키 안내 트리거 안내)
        hint_label = QLabel("💡  <b>Shift + ?</b> 를 누르면 단축키 안내창이 열립니다")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        hint_label.setTextFormat(Qt.TextFormat.RichText)
        hint_label.setStyleSheet(
            "color: #3d4f61; font-size: 11px;"
            "font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;"
            "background: transparent; padding: 2px 4px;"
        )
        layout.addWidget(hint_label)

        # 키보드 이벤트의 즉각 수신을 위해 본체 윈도우 포커스 고정
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
        
        # 비동기로 카메라 컨트롤러 초기화 수행
        self.run_in_background(self._init_camera_ctrl)
        self.update_status_display()

    def update_image(self, img):
        pix = QPixmap.fromImage(img).scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.video_label.setPixmap(pix)

    def update_status_msg(self, msg):
        self.update_status_display(extra=msg)

    def update_status_display(self, extra=None):
        if extra is not None:
            self.current_status = extra
            
        config = CAMERA_CONFIGS[self.current_camera_id]
        
        # 상태에 따른 텍스트 및 색상/배경 결정 (HTML 렌더링용)
        status_text = self.current_status
        bg_color = "rgba(245, 176, 65, 0.15)"
        text_color = "#f5b041"
        
        if status_text:
            if "실패" in status_text or "끊김" in status_text or "에러" in status_text:
                bg_color = "rgba(231, 76, 60, 0.15)"
                text_color = "#e74c3c"
            elif "완료" in status_text or "성공" in status_text or "연결 완료" in status_text:
                bg_color = "rgba(46, 204, 113, 0.15)"
                text_color = "#2ecc71"
                
        # 리치 텍스트 배지(Badge) 조립
        cam_badge = f"<span style='background-color: #2b3545; color: #ffffff; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>🎥 {config['name']}</span>"
        status_badge = f"<span style='background-color: {bg_color}; color: {text_color}; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>{status_text}</span>"
        
        # 입력 프리셋 상태
        if self.preset_buffer:
            preset_badge = f"<span style='background-color: rgba(52, 152, 219, 0.2); color: #3498db; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>입력 중: {self.preset_buffer}</span>"
        else:
            preset_badge = "<span style='color: #7f8c8d; padding: 3px 8px;'>입력 대기</span>"
            
        # 최근 성공적으로 보낸 프리셋
        last_badge = f"<span style='background-color: rgba(26, 188, 156, 0.2); color: #1abc9c; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>최근 프리셋: {self.last_preset}</span>"
        
        # 속도 조정 모드 배지 (활성화 시에만 표시)
        speed_badge = ""
        if self.speed_mode == 'pan_tilt':
            speed_badge = f" &nbsp; <span style='background-color: rgba(155, 89, 182, 0.25); color: #c39bd3; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>🎚️ 팬틸트 속도: {self.pan_tilt_speed} / 24 &nbsp; (+/- 조절, Z로 종료)</span>"
        elif self.speed_mode == 'zoom':
            speed_badge = f" &nbsp; <span style='background-color: rgba(52, 152, 219, 0.25); color: #7fb3d3; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>🔍 줌 속도: {self.zoom_speed} / 9 &nbsp; (+/- 조절, X로 종료)</span>"

        # 오버레이 꺼짐 배지 (OFF 상태일 때만 표시)
        overlay_badge = ""
        if not self.show_overlay:
            overlay_badge = " &nbsp; <span style='background-color: rgba(80, 80, 80, 0.2); color: #666; border-radius: 4px; padding: 3px 8px; font-weight: bold;'>🔲 오버레이 OFF</span>"

        # 가로 나열
        self.status_label.setText(f"{cam_badge} &nbsp; {status_badge} &nbsp; {preset_badge} &nbsp; {last_badge}{speed_badge}{overlay_badge}")
        
        # 2. 우측 계산기 패널 업데이트 (수식과 결과를 다르게 스타일링)
        if self.calc_buffer:
            if "=" in self.calc_buffer:
                expr, val = self.calc_buffer.split("=", 1)
                calc_html = f"<span style='color: #64748b; font-size: 13px;'>{expr} =</span> <span style='color: #00ffd2; font-size: 15px; font-weight: bold;'>{val}</span>"
            else:
                calc_html = f"<span style='color: #e2e8f0; font-size: 14px;'>{self.calc_buffer}</span>"
        else:
            calc_html = "<span style='color: #475569; font-size: 12px; font-style: italic;'>🔢 텐키 수식 입력 대기</span>"
            
        self.calc_label.setText(calc_html)

    def _init_camera_ctrl(self):
        config = CAMERA_CONFIGS[self.current_camera_id]
        try:
            self.camera = CameraController(config["ctrl_ip"], "admin", "admin", port=config["ctrl_port"])
        except Exception:
            self.camera = None

    def run_in_background(self, func, *args):
        """
        네트워크(requests) 호출 시 GUI 메인 스레드가 멈추는(블로킹) 현상을 원천 방지하기 위해
        모든 카메라 제어 송신 작업을 백그라운드 데몬 스레드로 비동기 처리합니다.
        """
        t = threading.Thread(target=func, args=args, daemon=True)
        t.start()

    def _bg_move_to_preset(self, preset_num):
        if self.camera:
            self.camera.move_to_preset(preset_num)

    def _bg_start_move(self, direction):
        if self.camera:
            if direction in ["zoomin", "zoomout"]:
                self.camera.move_continuous(direction, self.zoom_speed)
            else:
                self.camera.move_continuous(direction, self.pan_tilt_speed, self.pan_tilt_speed)

    def _bg_stop_move(self, cmd):
        if self.camera:
            self.camera.stop_movement(cmd)

    def move_to_preset(self):
        if not self.preset_buffer:
            return
        preset_num = int(self.preset_buffer)
        self.last_preset = str(preset_num)
        # 백그라운드로 전송하여 GUI 프리징 차단
        self.run_in_background(self._bg_move_to_preset, preset_num)
        self.preset_buffer = ""
        self.update_status_display()

    def start_move(self, direction):
        self.run_in_background(self._bg_start_move, direction)

    def stop_move(self, cmd="move"):
        self.run_in_background(self._bg_stop_move, cmd)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        text = event.text().lower()
        modifiers = event.modifiers()
        is_keypad = bool(modifiers & Qt.KeyboardModifier.KeypadModifier)
        
        # 연속 입력(Auto Repeat)을 허용할 키만 선별적으로 통과시킴
        # 허용: Backspace (수식 연속 삭제), +/- (속도 연속 조절)
        is_speed_plus  = text in ['+', '='] and self.speed_mode is not None
        is_speed_minus = text == '-' and self.speed_mode is not None
        is_calc_backspace = key == Qt.Key.Key_Backspace and self.calc_buffer
        allow_repeat = is_speed_plus or is_speed_minus or is_calc_backspace
        
        if event.isAutoRepeat() and not allow_repeat:
            return

        # F1, F2, F3: 카메라 전환
        if key == Qt.Key.Key_F1:
            self.start_stream(1)
            return
        elif key == Qt.Key.Key_F2:
            self.start_stream(2)
            return
        elif key == Qt.Key.Key_F3:
            self.start_stream(3)
            return

        # Shift + ?: 단축키 안내 모달 열기
        if text == '?':
            modal = HelpModal(self)
            modal.exec()
            return

        # Z: 팬틸트 속도 조정 모드 토글
        if key == Qt.Key.Key_Z or text == 'ㅋ':
            if self.speed_mode == 'pan_tilt':
                self.speed_mode = None
            else:
                self.speed_mode = 'pan_tilt'
            self.update_status_display()
            return

        # X: 줌 속도 조정 모드 토글
        if key == Qt.Key.Key_X or text == 'ㅌ':
            if self.speed_mode == 'zoom':
                self.speed_mode = None
            else:
                self.speed_mode = 'zoom'
            self.update_status_display()
            return

        # H: 십자 / 9분할 오버레이 토글
        if key == Qt.Key.Key_H or text == 'ㅗ':
            self.show_overlay = not self.show_overlay
            self.video_label.show_overlay = self.show_overlay
            self.video_label.update()
            self.update_status_display()
            return

        # 속도 조정 모드가 활성화된 경우 +/- 처리
        if self.speed_mode == 'pan_tilt':
            if text in ['+', '=']:
                self.pan_tilt_speed = min(24, self.pan_tilt_speed + 1)
                self.update_status_display()
                return
            elif text == '-':
                self.pan_tilt_speed = max(1, self.pan_tilt_speed - 1)
                self.update_status_display()
                return
        elif self.speed_mode == 'zoom':
            if text in ['+', '=']:
                self.zoom_speed = min(9, self.zoom_speed + 1)
                self.update_status_display()
                return
            elif text == '-':
                self.zoom_speed = max(1, self.zoom_speed - 1)
                self.update_status_display()
                return

        # WASD: 상/좌/하/우 카메라 이동
        if key == Qt.Key.Key_W or text == 'ㅈ':
            self.start_move("up")
            return
        elif key == Qt.Key.Key_S or text == 'ㄴ':
            self.start_move("down")
            return
        elif key == Qt.Key.Key_A or text == 'ㅁ':
            self.start_move("left")
            return
        elif key == Qt.Key.Key_D or text == 'ㅇ':
            self.start_move("right")
            return
            
        # QE: 줌 제어
        elif key == Qt.Key.Key_Q or text == 'ㅂ':
            self.start_move("zoomin")
            return
        elif key == Qt.Key.Key_E or text == 'ㄷ':
            self.start_move("zoomout")
            return

        # ----------------- 계산기 입력 (우측 텐키 영역) -----------------
        # 텐키 엔터 키 처리
        if is_keypad and (key == Qt.Key.Key_Enter or key == Qt.Key.Key_Return):
            self.evaluate_calculator()
            return
            
        if is_keypad:
            # 텐키 숫자 입력
            if text.isdigit() and len(text) == 1:
                if "=" in self.calc_buffer or "Error" in self.calc_buffer:
                    self.calc_buffer = ""
                self.calc_buffer += text
                self.update_status_display()
                return
            # 텐키 사칙연산 기호
            elif text in ['+', '-', '*', '/']:
                if "=" in self.calc_buffer or "Error" in self.calc_buffer:
                    self.calc_buffer = self.calc_result + text
                else:
                    self.calc_buffer += text
                self.update_status_display()
                return
            # 텐키 소수점 (.)
            elif text == '.':
                if "=" in self.calc_buffer or "Error" in self.calc_buffer:
                    self.calc_buffer = ""
                self.calc_buffer += text
                self.update_status_display()
                return

        # ----------------- 프리셋 입력 (좌측 일반 숫자 영역) -----------------
        # 일반 숫자 키패드가 아닌 곳에서 0~9 입력
        if text.isdigit() and len(text) == 1 and not is_keypad:
            self.preset_buffer += text
            self.update_status_display()
            return

        # Spacebar: 프리셋 이동 확정
        elif key == Qt.Key.Key_Space:
            self.move_to_preset()
            return

        # Backspace, Escape 역할 격리 및 세분화
        elif key == Qt.Key.Key_Backspace:
            if self.calc_buffer:
                if "Error" in self.calc_buffer:
                    self.calc_buffer = ""
                    self.calc_result = ""
                elif "=" in self.calc_buffer:
                    # 이미 결과가 도출된 상태에서 지우면 결과 등호와 값을 지우고 원래 입력식으로 롤백
                    self.calc_buffer = self.calc_buffer.split("=")[0]
                    self.calc_result = ""
                else:
                    # 일반 수식 입력 시 한 글자씩 지움
                    self.calc_buffer = self.calc_buffer[:-1]
            self.update_status_display()
            return
            
        elif key == Qt.Key.Key_Escape:
            # ESC는 오직 프리셋 버퍼만 클리어
            self.preset_buffer = ""
            self.update_status_display()
            return

    def evaluate_calculator(self):
        if not self.calc_buffer or "=" in self.calc_buffer or "Error" in self.calc_buffer:
            return
        
        # 보안 및 정합성을 위해 텐키 연산 가능한 문자만 필터링
        cleaned_expr = "".join(c for c in self.calc_buffer if c in "0123456789+-*/.")
        if not cleaned_expr:
            return
            
        # 끝에 연산자(+, -, *, /)나 소수점(.)이 붙어 있는 경우 제거 (예: "4+25+" -> "4+25")
        while cleaned_expr and cleaned_expr[-1] in "+-*/.":
            cleaned_expr = cleaned_expr[:-1]
            
        if not cleaned_expr:
            return
            
        try:
            # 수식 평가 수행
            result = eval(cleaned_expr)
            # 결과가 정수 소수점(.0)으로 끝나면 정수로 단순화
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            # 소수일 경우 가독성을 위해 최대 소수점 4자리까지 표현
            elif isinstance(result, float):
                result = round(result, 4)
                
            self.calc_result = str(result)
            # 깔끔하게 정리된 수식과 결과를 함께 표시 (예: 4+25=29)
            self.calc_buffer = f"{cleaned_expr}={self.calc_result}"
        except Exception:
            self.calc_buffer = "Error"
            self.calc_result = ""
            
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
    window = NewControlGUI()
    window.show()
    sys.exit(app.exec())
