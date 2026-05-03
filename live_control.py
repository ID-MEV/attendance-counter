import sys
import cv2
import logging
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QGroupBox, QPlainTextEdit, QFormLayout)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from camera_controller import CameraController
from logger_setup import logger

class LiveVideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    raw_frame_signal = pyqtSignal(object)

    def __init__(self, rtsp_url):
        super().__init__()
        self.rtsp_url = rtsp_url
        self._run_flag = True

    def run(self):
        cap = cv2.VideoCapture(self.rtsp_url)
        while self._run_flag:
            ret, frame = cap.read()
            if ret:
                self.raw_frame_signal.emit(frame)
                # GUI 표시용 변환
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.change_pixmap_signal.emit(qt_image)
            else:
                self.msleep(100)
                cap.open(self.rtsp_url)
        cap.release()

    def stop(self):
        self._run_flag = False
        self.wait()

class LiveControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera = CameraController("192.168.0.90", "admin", "admin")
        self.rtsp_url = "rtsp://mev.o-r.kr:20003/stream1"
        self.latest_frame = None
        self.init_ui()
        
        # 비디오 스레드 자동 시작
        self.video_thread = LiveVideoThread(self.rtsp_url)
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.raw_frame_signal.connect(self.update_raw_frame)
        self.video_thread.start()

    def init_ui(self):
        self.setWindowTitle("성림 카메라 라이브 컨트롤러")
        self.setGeometry(150, 150, 1100, 700)
        self.setStyleSheet("""
            QMainWindow { background-color: #2c3e50; }
            QLabel { color: white; font-weight: bold; }
            QGroupBox { color: #ecf0f1; font-weight: bold; border: 1px solid #7f8c8d; margin-top: 10px; }
            QPushButton { background-color: #3498db; color: white; padding: 8px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #2980b9; }
            QPlainTextEdit { background-color: #ecf0f1; color: #2c3e50; font-family: 'Consolas'; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # --- 왼쪽: 실시간 영상 ---
        left_layout = QVBoxLayout()
        self.video_label = QLabel("스트림 연결 중...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; border: 2px solid #34495e;")
        self.video_label.setMinimumSize(800, 500)
        left_layout.addWidget(self.video_label)
        
        main_layout.addLayout(left_layout, 7)

        # --- 오른쪽: 컨트롤 패널 ---
        right_layout = QVBoxLayout()

        # 1. 프리셋 이동 섹션
        move_group = QGroupBox("카메라 제어")
        move_layout = QFormLayout()
        self.preset_input = QLineEdit()
        self.preset_input.setPlaceholderText("번호 입력 (예: 2)")
        self.move_btn = QPushButton("프리셋 이동")
        self.move_btn.clicked.connect(self.move_to_preset)
        
        self.capture_btn = QPushButton("현재 화면 저장 (Snapshot)")
        self.capture_btn.setStyleSheet("background-color: #27ae60;")
        self.capture_btn.clicked.connect(self.capture_snapshot)
        
        move_layout.addRow("프리셋 번호:", self.preset_input)
        move_layout.addWidget(self.move_btn)
        move_layout.addWidget(self.capture_btn)
        move_group.setLayout(move_layout)
        right_layout.addWidget(move_group)

        # 2. 작업 로그 섹션
        log_group = QGroupBox("작업 로그")
        log_layout = QVBoxLayout()
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group, 1) # 로그 창이 남은 공간을 차지하도록

        main_layout.addLayout(right_layout, 3)

        self.add_log("라이브 컨트롤러가 시작되었습니다.")

    def update_image(self, qt_img):
        pixmap = QPixmap.fromImage(qt_img)
        p = pixmap.scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
        self.video_label.setPixmap(p)

    def update_raw_frame(self, frame):
        self.latest_frame = frame

    def capture_snapshot(self):
        if self.latest_frame is None:
            self.add_log("[오류] 캡처할 프레임이 없습니다.")
            return

        save_dir = "captures"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            
        preset_no = self.preset_input.text().strip() or "Live"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"snapshot_P{preset_no}_{timestamp}.jpg"
        file_path = os.path.join(save_dir, file_name)
        
        cv2.imwrite(file_path, self.latest_frame)
        self.add_log(f"[캡처 성공] {file_name} 저장 완료")

    def move_to_preset(self):
        preset_text = self.preset_input.text().strip()
        if not preset_text.isdigit():
            self.add_log("[오류] 유효한 숫자를 입력하세요.")
            return

        preset_no = int(preset_text)
        self.add_log(f"명령: 프리셋 {preset_no}번으로 이동 시도...")
        
        success, msg = self.camera.move_to_preset(preset_no)
        if success:
            self.add_log(f"[성공] 프리셋 {preset_no}번 이동 중")
        else:
            self.add_log(f"[실패] {msg}")

    def add_log(self, text):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_display.appendPlainText(f"[{now}] {text}")
        logger.info(f"UI Log: {text}")

    def closeEvent(self, event):
        self.video_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LiveControlGUI()
    window.show()
    sys.exit(app.exec())
