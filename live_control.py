import sys
import cv2
import logging
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QGroupBox, QPlainTextEdit, QFormLayout, QGridLayout,
                             QFrame)
from PyQt6.QtGui import QImage, QPixmap, QKeyEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from camera_controller import CameraController
from detector import PersonDetector
from logger_setup import logger

# 카메라 스트림 및 제어 정보 설정 (작업 지시서 기반)
CAMERA_CONFIGS = {
    1: {
        "name": "예배당 좌측 (1번)",
        "srt_main": "srt://mev.o-r.kr:20001",
        "rtsp_main": "rtsp://mev.o-r.kr:20001/stream1",
        "srt_sub": "srt://mev.o-r.kr:20001",
        "rtsp_sub": "rtsp://mev.o-r.kr:20001/stream2",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 8001
    },
    2: {
        "name": "예배당 중앙 (2번)",
        "srt_main": "srt://mev.o-r.kr:20002",
        "rtsp_main": "rtsp://mev.o-r.kr:20002/stream1",
        "srt_sub": "srt://mev.o-r.kr:20002",
        "rtsp_sub": "rtsp://mev.o-r.kr:20002/stream2",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 8002
    },
    3: {
        "name": "예배당 우측 (3번)",
        "srt_main": "srt://mev.o-r.kr:20003",
        "rtsp_main": "rtsp://mev.o-r.kr:20003/stream1",
        "srt_sub": "srt://mev.o-r.kr:20003",
        "rtsp_sub": "rtsp://mev.o-r.kr:20003/stream2",
        "ctrl_ip": "mev.o-r.kr",
        "ctrl_port": 8003
    }
}

class SubPreviewThread(QThread):
    """
    하단 서브 프리뷰 화면 전용 스레드 (항상 저해상도 .../stream2 수신)
    """
    change_pixmap_signal = pyqtSignal(QImage, int)
    stream_status_signal = pyqtSignal(bool, str, int)

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
        logger.info(f"[서브스레드 {self.camera_id}번] 연결 시도 시작...")
        
        while self._run_flag:
            if not self.is_connected:
                # 1. SRT 우선 연결 시도
                logger.info(f"[서브스레드 {self.camera_id}번] SRT 연결 시도: {self.srt_url}")
                self._cap = cv2.VideoCapture(self.srt_url, cv2.CAP_FFMPEG)
                if self._cap.isOpened():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        self.is_connected = True
                        self.active_protocol = "SRT"
                        self.stream_status_signal.emit(True, f"SRT 연결 성공 (서브)", self.camera_id)
                        # 첫 프레임 즉시 전송
                        self.emit_frame(frame)
                
                # 2. SRT 실패 시 RTSP 폴백 시도
                if not self.is_connected:
                    if self._cap:
                        self._cap.release()
                    logger.warning(f"[서브스레드 {self.camera_id}번] SRT 실패, RTSP 폴백 시도: {self.rtsp_url}")
                    self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                    if self._cap.isOpened():
                        ret, frame = self._cap.read()
                        if ret and frame is not None:
                            self.is_connected = True
                            self.active_protocol = "RTSP"
                            self.stream_status_signal.emit(True, f"RTSP 폴백 성공 (서브)", self.camera_id)
                            self.emit_frame(frame)
                
                # 둘 다 실패 시 대기 후 재시도
                if not self.is_connected:
                    self.stream_status_signal.emit(False, "연결 실패 (재시도 대기)", self.camera_id)
                    self.msleep(5000)
                    continue

            # 연결 성공 상태 루프
            ret, frame = self._cap.read()
            if ret and frame is not None:
                self.emit_frame(frame)
            else:
                logger.warning(f"[서브스레드 {self.camera_id}번] 스트림 유실. 재연결 시도...")
                self.is_connected = False
                self.active_protocol = "None"
                if self._cap:
                    self._cap.release()
                self.stream_status_signal.emit(False, "스트림 유실됨", self.camera_id)
                self.msleep(1000)

        if self._cap:
            self._cap.release()

    def emit_frame(self, frame):
        try:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = rgb_image.strides[0]
            qt_image = QImage(rgb_image.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.change_pixmap_signal.emit(qt_image.copy(), self.camera_id)
        except Exception as e:
            logger.error(f"[서브스레드 {self.camera_id}번] 프레임 방출 에러: {e}")

    def stop(self):
        self._run_flag = False
        self.wait()


class MainViewThread(QThread):
    """
    상단 메인 뷰 화면 전용 스레드 (선택된 메인 카메라의 고해상도 .../stream1 수신 및 실시간 YOLO 탐지)
    """
    change_pixmap_signal = pyqtSignal(QImage, int)
    raw_frame_signal = pyqtSignal(object, int)
    stream_status_signal = pyqtSignal(bool, str, int)
    count_signal = pyqtSignal(int)

    def __init__(self, camera_id, srt_url, rtsp_url, detector):
        super().__init__()
        self.camera_id = camera_id
        self.srt_url = srt_url
        self.rtsp_url = rtsp_url
        self.detector = detector
        self._run_flag = True
        self._cap = None
        self.is_connected = False
        self.active_protocol = "None"
        self.is_detection_enabled = True # 실시간 YOLO 탐지 기본 활성화

    def run(self):
        logger.info(f"[메인스레드 {self.camera_id}번] 고해상도 연결 시도 시작...")
        
        while self._run_flag:
            if not self.is_connected:
                # 1. SRT 우선 연결 시도
                logger.info(f"[메인스레드 {self.camera_id}번] SRT 연결 시도: {self.srt_url}")
                self._cap = cv2.VideoCapture(self.srt_url, cv2.CAP_FFMPEG)
                if self._cap.isOpened():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        self.is_connected = True
                        self.active_protocol = "SRT"
                        self.stream_status_signal.emit(True, f"SRT 연결 성공 ({self.active_protocol})", self.camera_id)
                        self.process_and_emit(frame)
                
                # 2. SRT 실패 시 RTSP 폴백 시도
                if not self.is_connected:
                    if self._cap:
                        self._cap.release()
                    logger.warning(f"[메인스레드 {self.camera_id}번] SRT 실패, RTSP 폴백 시도: {self.rtsp_url}")
                    self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                    if self._cap.isOpened():
                        ret, frame = self._cap.read()
                        if ret and frame is not None:
                            self.is_connected = True
                            self.active_protocol = "RTSP"
                            self.stream_status_signal.emit(True, f"RTSP 폴백 성공 ({self.active_protocol})", self.camera_id)
                            self.process_and_emit(frame)
                
                # 둘 다 실패 시 대기 후 재시도
                if not self.is_connected:
                    self.stream_status_signal.emit(False, "연결 실패 (재시도 대기)", self.camera_id)
                    self.msleep(4000)
                    continue

            # 연결 성공 상태 루프
            ret, frame = self._cap.read()
            if ret and frame is not None:
                self.process_and_emit(frame)
            else:
                logger.warning(f"[메인스레드 {self.camera_id}번] 스트림 유실. 재연결 시도...")
                self.is_connected = False
                self.active_protocol = "None"
                if self._cap:
                    self._cap.release()
                self.stream_status_signal.emit(False, "스트림 유실됨", self.camera_id)
                self.msleep(1000)

        if self._cap:
            self._cap.release()

    def process_and_emit(self, frame):
        try:
            self.raw_frame_signal.emit(frame, self.camera_id)
            
            # 실시간 YOLO 객체 탐지 수행 (Main View에서만 수행)
            if self.is_detection_enabled:
                count, annotated_frame, _ = self.detector.detect_people(frame, conf_threshold=0.15)
                self.count_signal.emit(count)
                display_frame = annotated_frame
            else:
                self.count_signal.emit(0)
                display_frame = frame
            
            rgb_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = rgb_image.strides[0]
            qt_image = QImage(rgb_image.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.change_pixmap_signal.emit(qt_image.copy(), self.camera_id)
        except Exception as e:
            logger.error(f"[메인스레드 {self.camera_id}번] 프레임 분석/방출 에러: {e}")

    def stop(self):
        self._run_flag = False
        self.wait()


class LiveControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.detector = PersonDetector()
        
        self.current_main_camera = 3  # 기본 메인 카메라: 3번
        self.latest_frame = None
        
        self.sub_threads = {}
        self.main_thread = None
        
        self.init_ui()
        self.start_all_streams()

    def init_ui(self):
        self.setWindowTitle("성림 멀티카메라 라이브 인원분석 컨트롤러 v2.0")
        self.setGeometry(100, 100, 1280, 850)
        
        # 프리미엄 다크 모드 스타일 시트 적용
        self.setStyleSheet("""
            QMainWindow { background-color: #121418; }
            QLabel { color: #e0e6ed; font-family: 'Segoe UI', 'Apple SD Gothic Neo', sans-serif; font-size: 13px; }
            QGroupBox {
                color: #58d68d;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #2c303b;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #1a1d24;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #2c303b;
                color: #e0e6ed;
                border: 1px solid #3d4354;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #3d4354;
                border-color: #5dade2;
            }
            QPushButton#primary {
                background-color: #2ecc71;
                color: white;
                border: none;
            }
            QPushButton#primary:hover {
                background-color: #27ae60;
            }
            QPushButton#accent {
                background-color: #3498db;
                color: white;
                border: none;
            }
            QPushButton#accent:hover {
                background-color: #2980b9;
            }
            QPushButton#warning {
                background-color: #e74c3c;
                color: white;
                border: none;
            }
            QPushButton#warning:hover {
                background-color: #c0392b;
            }
            QLineEdit {
                background-color: #121418;
                color: #e0e6ed;
                border: 1px solid #2c303b;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #5dade2;
            }
            QPlainTextEdit {
                background-color: #0f1115;
                color: #a0aec0;
                border: 1px solid #2c303b;
                border-radius: 6px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # ==================== [좌측: 비디오 스트리밍 존] ====================
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        
        # 1. 상단 (Main View) 큰 화면
        self.video_label = QLabel("메인 영상 로딩 중...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #08090b; border: 2px solid #2c303b; border-radius: 6px;")
        self.video_label.setMinimumSize(820, 480)
        left_layout.addWidget(self.video_label)
        
        # 2. 하단 (Sub Preview) 3분할 구조
        sub_videos_layout = QHBoxLayout()
        sub_videos_layout.setSpacing(10)
        
        self.sub_widgets = {}
        for i in [1, 2, 3]:
            sub_frame = QFrame()
            sub_frame.setFixedSize(266, 170)
            sub_frame.setStyleSheet("background-color: #08090b; border-radius: 6px;")
            
            sub_frame_lay = QVBoxLayout(sub_frame)
            sub_frame_lay.setContentsMargins(0, 0, 0, 0)
            sub_frame_lay.setSpacing(0)
            
            # 카메라 이름 라벨 추가
            cam_name_lbl = QLabel(f"  {CAMERA_CONFIGS[i]['name']}")
            cam_name_lbl.setStyleSheet("background-color: rgba(26, 29, 36, 0.9); font-size: 11px; font-weight: bold; padding: 4px; color: #58d68d; border-top-left-radius: 6px; border-top-right-radius: 6px;")
            sub_frame_lay.addWidget(cam_name_lbl)
            
            # 비디오 출력 라벨
            sub_label = QLabel(f"{i}번 대기 중...")
            sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_label.setStyleSheet("color: #7f8c8d; font-size: 11px; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
            sub_frame_lay.addWidget(sub_label)
            
            sub_videos_layout.addWidget(sub_frame)
            self.sub_widgets[i] = {
                "frame": sub_frame,
                "label": sub_label,
                "title": cam_name_lbl
            }
            
        left_layout.addLayout(sub_videos_layout)
        
        # 하단 조작 보조 버튼
        stream_ctrl_lay = QHBoxLayout()
        self.start_btn = QPushButton("전체 카메라 연결")
        self.start_btn.setObjectName("accent")
        self.start_btn.clicked.connect(self.start_all_streams)
        self.start_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.stop_btn = QPushButton("전체 연결 해제")
        self.stop_btn.setObjectName("warning")
        self.stop_btn.clicked.connect(self.stop_all_streams)
        self.stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.detection_toggle_btn = QPushButton("AI 실시간 분석 토글 (F)")
        self.detection_toggle_btn.clicked.connect(self.toggle_ai_detection)
        self.detection_toggle_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        stream_ctrl_lay.addWidget(self.start_btn)
        stream_ctrl_lay.addWidget(self.stop_btn)
        stream_ctrl_lay.addWidget(self.detection_toggle_btn)
        left_layout.addLayout(stream_ctrl_lay)
        
        main_layout.addLayout(left_layout, 7)

        # ==================== [우측: 컨트롤 및 데이터 존] ====================
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)

        # 1. 최상단: 현재 메인 카메라 상태 정보 및 실시간 인원 카운트
        status_group = QGroupBox("실시간 모니터링 상태")
        status_lay = QVBoxLayout()
        
        self.cam_info_name = QLabel("선택된 카메라: -")
        self.cam_info_name.setStyleSheet("font-size: 14px; font-weight: bold; color: #58d68d;")
        self.cam_info_url = QLabel("RTSP 주소: -")
        self.cam_info_url.setStyleSheet("font-size: 11px; color: #a0aec0;")
        self.cam_info_protocol = QLabel("연결 프로토콜: SRT (최선)")
        self.cam_info_protocol.setStyleSheet("font-size: 11px; color: #f1c40f;")
        
        status_lay.addWidget(self.cam_info_name)
        status_lay.addWidget(self.cam_info_url)
        status_lay.addWidget(self.cam_info_protocol)
        
        # 초대형 실시간 인원수 패널
        count_panel = QFrame()
        count_panel.setStyleSheet("background-color: #0f1115; border-radius: 6px; border: 1px solid #2c303b; margin-top: 5px;")
        count_panel_lay = QVBoxLayout(count_panel)
        
        count_title = QLabel("실시간 인원 계수")
        count_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_title.setStyleSheet("font-size: 12px; color: #a0aec0; font-weight: bold;")
        
        self.person_count_label = QLabel("0 명")
        self.person_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.person_count_label.setStyleSheet("font-size: 38px; color: #f1c40f; font-weight: 900; font-family: 'Segoe UI', Arial;")
        
        count_panel_lay.addWidget(count_title)
        count_panel_lay.addWidget(self.person_count_label)
        status_lay.addWidget(count_panel)
        
        status_group.setLayout(status_lay)
        right_layout.addWidget(status_group)

        # 2. 중간: 프리셋 & 제어 (프리셋 입력 + WASD 제어 + 즐겨찾기)
        control_group = QGroupBox("카메라 팬틸트/줌 & 프리셋 제어")
        control_lay = QVBoxLayout()
        
        # 프리셋 수동 입력창 & 스냅샷
        preset_form = QFormLayout()
        self.preset_input = QLineEdit()
        self.preset_input.setPlaceholderText("프리셋 번호 (1-254)")
        self.preset_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.move_btn = QPushButton("프리셋 이동 (Enter)")
        self.move_btn.clicked.connect(self.move_to_preset)
        self.move_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.capture_btn = QPushButton("스냅샷 저장 (C)")
        self.capture_btn.setObjectName("primary")
        self.capture_btn.clicked.connect(self.capture_snapshot)
        self.capture_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        preset_form.addRow("프리셋 번호:", self.preset_input)
        preset_form.addWidget(self.move_btn)
        preset_form.addWidget(self.capture_btn)
        control_lay.addLayout(preset_form)
        
        # 자주 쓰는 프리셋 즐겨찾기 신설
        fav_group = QGroupBox("★ 프리셋 즐겨찾기 (원클릭)")
        fav_group.setStyleSheet("margin-top: 5px; background-color: #121418; color: #f1c40f;")
        fav_lay = QHBoxLayout()
        fav_lay.setSpacing(5)
        fav_lay.setContentsMargins(5, 10, 5, 5)
        for preset_num in [1, 2, 3, 4]:
            btn = QPushButton(f"P{preset_num}")
            btn.setFixedWidth(55)
            btn.setStyleSheet("font-size: 11px; background-color: #1a1d24; border-color: #2c303b;")
            btn.clicked.connect(lambda checked, p=preset_num: self.move_to_specific_preset(p))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            fav_lay.addWidget(btn)
        fav_group.setLayout(fav_lay)
        control_lay.addWidget(fav_group)

        # 연속 PTZ 버튼 레이아웃 (WASD/QE)
        ptz_dir_group = QGroupBox("연속 PTZ 조작 (WASD / QE)")
        ptz_dir_group.setStyleSheet("margin-top: 5px; background-color: #121418;")
        ptz_grid = QGridLayout()
        ptz_grid.setSpacing(5)
        ptz_grid.setContentsMargins(5, 10, 5, 5)
        
        self.up_btn = QPushButton("▲ Up (W)")
        self.down_btn = QPushButton("▼ Down (S)")
        self.left_btn = QPushButton("◀ Left (A)")
        self.right_btn = QPushButton("▶ Right (D)")
        
        self.zoom_in_btn = QPushButton("Zoom + (Q)")
        self.zoom_out_btn = QPushButton("Zoom - (E)")
        
        for btn in [self.up_btn, self.down_btn, self.left_btn, self.right_btn, self.zoom_in_btn, self.zoom_out_btn]:
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet("font-size: 11px; padding: 6px;")
            
        ptz_grid.addWidget(self.up_btn, 0, 1)
        ptz_grid.addWidget(self.left_btn, 1, 0)
        ptz_grid.addWidget(self.right_btn, 1, 2)
        ptz_grid.addWidget(self.down_btn, 2, 1)
        
        ptz_grid.addWidget(self.zoom_in_btn, 3, 0)
        ptz_grid.addWidget(self.zoom_out_btn, 3, 2)
        ptz_dir_group.setLayout(ptz_grid)
        control_lay.addWidget(ptz_dir_group)
        
        control_group.setLayout(control_lay)
        right_layout.addWidget(control_group)

        # 3. 하단: 단축키 안내 및 로그 창
        self.key_status_label = QLabel("입력된 단축키: 없음")
        self.key_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_status_label.setStyleSheet("background-color: #2c303b; color: #58d68d; padding: 6px; border-radius: 4px; font-weight: bold; font-size: 12px;")
        right_layout.addWidget(self.key_status_label)
        
        log_group = QGroupBox("시스템 로그 콘솔")
        log_lay = QVBoxLayout()
        log_lay.setContentsMargins(5, 10, 5, 5)
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFixedHeight(160)
        self.log_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_lay.addWidget(self.log_display)
        
        # 키 가이드 인포 라벨
        guide_info = QLabel("F1/F2/F3: 메인 카메라 즉시 스위칭 | WASD: PTZ 조작 | Enter: 프리셋 이동")
        guide_info.setStyleSheet("font-size: 10px; color: #7f8c8d; font-weight: bold; margin-top: 2px;")
        log_lay.addWidget(guide_info)
        
        log_group.setLayout(log_lay)
        right_layout.addWidget(log_group)

        main_layout.addLayout(right_layout, 3)
        
        # 메인 윈도우 키 이벤트 활성화
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.add_log("멀티 카메라 라이브 분석 시스템 시작 완료.")

    def start_all_streams(self):
        """
        모든 카메라 스트림 연결 시작 (상단 고해상도 1개 + 하단 저해상도 3개)
        """
        self.stop_all_streams()
        self.add_log("모든 카메라 스트림 연결 시작 시도...")
        
        # 1. 하단 저해상도 서브 프리뷰 3개 상시 연결
        for cam_id, config in CAMERA_CONFIGS.items():
            self.add_log(f"-> 서브프리뷰 {cam_id}번 기동: {config['rtsp_sub']}")
            sub_thread = SubPreviewThread(cam_id, config["srt_sub"], config["rtsp_sub"])
            sub_thread.change_pixmap_signal.connect(self.update_sub_preview_image)
            sub_thread.stream_status_signal.connect(self.update_sub_stream_status)
            sub_thread.start()
            self.sub_threads[cam_id] = sub_thread
            
        # 2. 상단 고해상도 메인 뷰 연결 (현재 current_main_camera 기반)
        self.start_main_stream(self.current_main_camera)
        self.update_highlight_border()

    def start_main_stream(self, camera_id):
        """
        특정 카메라를 메인 고해상도 스레드로 기동
        """
        # 기존 메인 스레드가 있다면 정지
        if self.main_thread is not None:
            self.main_thread.stop()
            self.main_thread = None
            
        config = CAMERA_CONFIGS[camera_id]
        self.add_log(f"-> [메인 스트림 전환] {camera_id}번 고화질 기동: {config['rtsp_main']}")
        
        self.main_thread = MainViewThread(camera_id, config["srt_main"], config["rtsp_main"], self.detector)
        self.main_thread.change_pixmap_signal.connect(self.update_main_image)
        self.main_thread.raw_frame_signal.connect(self.update_raw_frame)
        self.main_thread.stream_status_signal.connect(self.update_main_stream_status)
        self.main_thread.count_signal.connect(self.update_person_count)
        self.main_thread.start()
        
        # UI 라벨 정보 갱신
        self.cam_info_name.setText(f"선택된 카메라: {config['name']}")
        self.cam_info_url.setText(f"RTSP: {config['rtsp_main']}")
        self.current_main_camera = camera_id
        
        # 카메라 하드웨어 컨트롤러 교체
        self._ensure_camera_initialized()

    def stop_all_streams(self):
        """
        모든 메인 및 서브 스레드 중단
        """
        self.add_log("모든 스트림 해제 시작...")
        if self.main_thread is not None:
            self.main_thread.stop()
            self.main_thread = None
            
        for cam_id, thread in list(self.sub_threads.items()):
            thread.stop()
        self.sub_threads.clear()
        
        # 비디오 표시 라벨 초기화
        self.video_label.setText("연결이 해제되었습니다.")
        self.video_label.setStyleSheet("background-color: #08090b; border: 2px solid #2c303b; border-radius: 6px; color: #7f8c8d;")
        for i in [1, 2, 3]:
            self.sub_widgets[i]["label"].setPixmap(QPixmap())
            self.sub_widgets[i]["label"].setText(f"{i}번 대기 중")
            self.sub_widgets[i]["frame"].setStyleSheet("background-color: #08090b; border-radius: 6px; border: 1px solid #2c303b;")
            
        self.person_count_label.setText("0 명")
        self.add_log("모든 스트림 연결이 해제되었습니다.")

    def update_sub_preview_image(self, img, camera_id):
        """
        서브 프리뷰 이미지 출력
        """
        lbl = self.sub_widgets[camera_id]["label"]
        pix = QPixmap.fromImage(img).scaled(lbl.width(), lbl.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        lbl.setPixmap(pix)

    def update_main_image(self, img, camera_id):
        """
        메인 뷰 이미지 출력
        """
        if camera_id == self.current_main_camera:
            pix = QPixmap.fromImage(img).scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.video_label.setPixmap(pix)

    def update_raw_frame(self, frame, camera_id):
        if camera_id == self.current_main_camera:
            self.latest_frame = frame

    def update_sub_stream_status(self, is_ok, msg, camera_id):
        frame_widget = self.sub_widgets[camera_id]["frame"]
        title_lbl = self.sub_widgets[camera_id]["title"]
        
        if not is_ok:
            title_lbl.setStyleSheet("background-color: rgba(192, 57, 43, 0.9); font-size: 11px; font-weight: bold; padding: 4px; color: white;")
            # 메인 선택 중이 아니면 연결 오류 붉은 테두리
            if camera_id != self.current_main_camera:
                frame_widget.setStyleSheet("background-color: #0d0404; border-radius: 6px; border: 2px solid #e74c3c;")
        else:
            title_lbl.setStyleSheet("background-color: rgba(26, 29, 36, 0.9); font-size: 11px; font-weight: bold; padding: 4px; color: #58d68d;")
            if camera_id == self.current_main_camera:
                frame_widget.setStyleSheet("background-color: #08090b; border-radius: 6px; border: 3px solid #2ecc71;")
            else:
                frame_widget.setStyleSheet("background-color: #08090b; border-radius: 6px; border: 1px solid #2c303b;")

    def update_main_stream_status(self, is_ok, msg, camera_id):
        self.add_log(f"[{CAMERA_CONFIGS[camera_id]['name']}] {msg}")
        if is_ok:
            self.cam_info_protocol.setText(f"연결 프로토콜: {self.main_thread.active_protocol}")
            self.video_label.setStyleSheet("background-color: black; border: 2px solid #2ecc71; border-radius: 6px;")
        else:
            self.cam_info_protocol.setText("연결 프로토콜: 실패")
            self.video_label.setText(f"메인 카메라 연결 실패 ({msg})")
            self.video_label.setStyleSheet("background-color: #1a0808; border: 2px solid #e74c3c; border-radius: 6px; color: white;")

    def update_person_count(self, count):
        self.person_count_label.setText(f"{count} 명")

    def toggle_ai_detection(self):
        if self.main_thread is not None:
            self.main_thread.is_detection_enabled = not self.main_thread.is_detection_enabled
            status_str = "활성화" if self.main_thread.is_detection_enabled else "비활성화"
            self.add_log(f"실시간 AI 객체 탐지: {status_str}")
            self.detection_toggle_btn.setText(f"AI 실시간 분석 토글 ({status_str})")

    def update_highlight_border(self):
        """
        메인으로 선택된 서브 프리뷰에 밝고 눈에 띄는 하이라이트 Border를 적용합니다.
        """
        for i in [1, 2, 3]:
            frame_widget = self.sub_widgets[i]["frame"]
            if i == self.current_main_camera:
                frame_widget.setStyleSheet("background-color: #08090b; border-radius: 6px; border: 3px solid #2ecc71;") # 눈에 띄는 형광녹색 테두리
            else:
                # 연결 상태에 맞게 기본 테두리 설정
                thread = self.sub_threads.get(i)
                is_connected = thread and thread.is_connected
                if is_connected:
                    frame_widget.setStyleSheet("background-color: #08090b; border-radius: 6px; border: 1px solid #2c303b;")
                else:
                    frame_widget.setStyleSheet("background-color: #08090b; border-radius: 6px; border: 1px solid #2c303b;")

    def _ensure_camera_initialized(self):
        config = CAMERA_CONFIGS[self.current_main_camera]
        expected_ip = config["ctrl_ip"]
        expected_port = config["ctrl_port"]
        
        # 카메라 기기가 바뀌었거나 미초기화 시에만 컨트롤러 재생성
        if self.camera is None or self.camera.ip != expected_ip or self.camera.port != expected_port:
            try:
                self.camera = CameraController(expected_ip, "admin", "admin", port=expected_port)
                self.add_log(f"카메라 {self.current_main_camera}번 PTZ 연결 완료 ({expected_ip}:{expected_port})")
                return True
            except Exception as e:
                self.add_log(f"[오류] PTZ 카메라 컨트롤러 연동 실패: {e}")
                return False
        return True

    def move_to_preset(self):
        val = self.preset_input.text().strip()
        if val.isdigit():
            preset_num = int(val)
            self.move_to_specific_preset(preset_num)
            self.preset_input.clear()

    def move_to_specific_preset(self, preset_num):
        self.add_log(f"명령: {self.current_main_camera}번 카메라 프리셋 {preset_num}번 이동")
        if self._ensure_camera_initialized():
            # 비동기 조작 권장이나 단발성은 바로 전송
            success, msg = self.camera.move_to_preset(preset_num)
            if success:
                self.add_log(f"-> 프리셋 {preset_num}번 이동 성공")
            else:
                self.add_log(f"[경고] 프리셋 이동 실패: {msg}")

    def capture_snapshot(self):
        if self.latest_frame is not None:
            save_dir = "captures"
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"snap_cam{self.current_main_camera}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
            cv2.imwrite(path, self.latest_frame)
            self.add_log(f"스냅샷 저장 성공: {path}")
        else:
            self.add_log("[오류] 저장할 캡처 프레임이 없습니다.")

    def start_continuous_move(self, direction, s1=10, s2=10):
        if self._ensure_camera_initialized():
            self.camera.move_continuous(direction, s1, s2)

    def stop_continuous_move(self, cmd="move"):
        if self._ensure_camera_initialized():
            self.camera.stop_movement(cmd)

    def keyPressEvent(self, event: QKeyEvent):
        if event.isAutoRepeat(): return
        key = event.key()
        text = event.text().lower()

        # 1. F1, F2, F3: 카메라 즉시 메인 스위칭 (작업 지시서 요구사항)
        if key in [Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3]:
            cam_map = {Qt.Key.Key_F1: 1, Qt.Key.Key_F2: 2, Qt.Key.Key_F3: 3}
            target_no = cam_map[key]
            self.key_status_label.setText(f"단축키: F{target_no} (카메라 {target_no} 스위칭)")
            self.start_main_stream(target_no)
            self.update_highlight_border()
            return

        # 2. WASD/QE 카메라 물리 팬틸트줌 제어
        if key == Qt.Key.Key_W or text == 'ㅈ': 
            self.key_status_label.setText("단축키: W (Up)"); self.start_continuous_move("up")
        elif key == Qt.Key.Key_S or text == 'ㄴ': 
            self.key_status_label.setText("단축키: S (Down)"); self.start_continuous_move("down")
        elif key == Qt.Key.Key_A or text == 'ㅁ': 
            self.key_status_label.setText("단축키: A (Left)"); self.start_continuous_move("left")
        elif key == Qt.Key.Key_D or text == 'ㅇ': 
            self.key_status_label.setText("단축키: D (Right)"); self.start_continuous_move("right")
        elif key == Qt.Key.Key_Q or text == 'ㅂ': 
            self.key_status_label.setText("단축키: Q (Zoom+)"); self.start_continuous_move("zoomin", 6, 6)
        elif key == Qt.Key.Key_E or text == 'ㄷ': 
            self.key_status_label.setText("단축키: E (Zoom-)"); self.start_continuous_move("zoomout", 6, 6)
            
        # 3. 단발성 제어 단축키 (C, F 등)
        elif key == Qt.Key.Key_C or text == 'ㅊ': 
            self.key_status_label.setText("단축키: C (스냅샷)"); self.capture_snapshot()
        elif key == Qt.Key.Key_F or text == 'ㄹ': 
            self.key_status_label.setText("단축키: F (AI 분석 토글)"); self.toggle_ai_detection()
            
        # 4. 프리셋 단축키 입력 매핑 (m,,. jkl uio ;)
        else:
            p_map = {Qt.Key.Key_M:'1', Qt.Key.Key_Comma:'2', Qt.Key.Key_Period:'3',
                     Qt.Key.Key_J:'4', Qt.Key.Key_K:'5', Qt.Key.Key_L:'6',
                     Qt.Key.Key_U:'7', Qt.Key.Key_I:'8', Qt.Key.Key_O:'9', Qt.Key.Key_Semicolon:'0'}
            k_map = {'ㅡ':'1','ㅓ':'4','ㅏ':'5','ㅣ':'6','ㅕ':'7','ㅑ':'8','ㅐ':'9',';':'0'}
            
            digit = p_map.get(key) or k_map.get(text)
            if text == ',': digit = '2'
            elif text == '.': digit = '3'
            
            if digit:
                self.preset_input.setText(self.preset_input.text() + digit)
                self.key_status_label.setText(f"프리셋 번호 입력 중: {self.preset_input.text()}")
                return

            # 엔터 입력 시 이동
            if key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
                self.move_to_preset()
            elif key == Qt.Key.Key_Backspace:
                self.preset_input.setText(self.preset_input.text()[:-1])
                self.key_status_label.setText(f"프리셋 번호 입력 중: {self.preset_input.text()}")
            elif key == Qt.Key.Key_Escape:
                self.preset_input.clear()
                self.key_status_label.setText("입력 정보 초기화됨")

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        key = event.key()
        text = event.text().lower()
        self.key_status_label.setText("입력된 단축키: 없음")
        
        if key in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D] or text in ['ㅈ','ㄴ','ㅁ','ㅇ']:
            self.stop_continuous_move("move")
        elif key in [Qt.Key.Key_Q, Qt.Key.Key_E] or text in ['ㅂ','ㄷ']:
            self.stop_continuous_move("zoom")

    def add_log(self, txt):
        self.log_display.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {txt}")
        logger.info(f"UI Console: {txt}")

    def closeEvent(self, event):
        self.stop_all_streams()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LiveControlGUI()
    window.show()
    sys.exit(app.exec())
