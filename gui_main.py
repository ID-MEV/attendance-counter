import sys
import cv2
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QGroupBox, QLineEdit, QFormLayout, QSpinBox)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from detector import PersonDetector
from sequence_manager import SequenceManager

class VideoThread(QThread):
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
                # 연결 실패 시 잠시 대기 후 재시도
                self.msleep(1000)
                cap.open(self.rtsp_url)
        cap.release()

    def stop(self):
        self._run_flag = False
        self.wait()

class ROIImageLabel(QLabel):
    roi_selected = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        self.begin = QPoint()
        self.end = QPoint()
        self.is_drawing = False
        self.current_roi = None

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.begin.isNull() and not self.end.isNull():
            painter = QPainter(self)
            painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.PenStyle.SolidLine))
            painter.drawRect(QRect(self.begin, self.end))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin = event.pos()
            self.end = event.pos()
            self.is_drawing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_drawing = False
            self.current_roi = QRect(self.begin, self.end).normalized()
            self.roi_selected.emit(self.current_roi)
            self.update()

class AttendanceGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.detector = PersonDetector()
        
        # 기본 설정
        self.camera_config = {
            'ip': '192.168.0.90',
            'user': 'admin',
            'password': 'admin'
        }
        self.rtsp_url = "rtsp://mev.o-r.kr:20003/stream1"
        self.presets_to_run = [1, 2] # 기본 프리셋
        
        self.seq_manager = SequenceManager(self.camera_config, self.detector)
        self.init_ui()
        
        self.video_thread = None
        self.latest_frame = None

    def init_ui(self):
        self.setWindowTitle("성림 출석 인원 카운터 v1.0")
        self.setGeometry(100, 100, 1200, 800)
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; }
            QPushButton { padding: 10px; font-weight: bold; border-radius: 5px; }
            QPushButton#primary { background-color: #2ecc71; color: white; }
            QPushButton#secondary { background-color: #3498db; color: white; }
            QLabel#status { background-color: #34495e; color: white; padding: 5px; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 왼쪽: 비디오 및 컨트롤
        left_layout = QVBoxLayout()
        
        # 이미지 레이블 (ROI 선택 기능 포함)
        self.image_label = ROIImageLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 2px solid #34495e; background-color: black;")
        self.image_label.setMinimumSize(800, 600)
        self.image_label.roi_selected.connect(self.on_roi_selected)
        left_layout.addWidget(self.image_label)

        # 하단 상태 바
        self.status_label = QLabel("준비 완료")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.status_label)
        
        main_layout.addLayout(left_layout, 7)

        # 오른쪽: 설정 및 결과
        right_layout = QVBoxLayout()
        
        # 설정 그룹
        config_group = QGroupBox("카메라 및 프리셋 설정")
        config_form = QFormLayout()
        self.rtsp_input = QLineEdit(self.rtsp_url)
        self.preset_input = QLineEdit(", ".join(map(str, self.presets_to_run)))
        config_form.addRow("RTSP URL:", self.rtsp_input)
        config_form.addRow("분석 프리셋(쉼표 구분):", self.preset_input)
        config_group.setLayout(config_form)
        right_layout.addWidget(config_group)

        # ROI 설정 그룹
        roi_group = QGroupBox("ROI 설정")
        roi_layout = QVBoxLayout()
        self.current_preset_spin = QSpinBox()
        self.current_preset_spin.setRange(1, 255)
        self.save_roi_btn = QPushButton("현재 영역을 프리셋 ROI로 저장")
        self.save_roi_btn.clicked.connect(self.save_current_roi)
        roi_layout.addWidget(QLabel("선택 중인 프리셋 번호:"))
        roi_layout.addWidget(self.current_preset_spin)
        roi_layout.addWidget(self.save_roi_btn)
        roi_group.setLayout(roi_layout)
        right_layout.addWidget(roi_group)

        # 동작 버튼
        self.stream_btn = QPushButton("스트리밍 시작")
        self.stream_btn.setObjectName("secondary")
        self.stream_btn.clicked.connect(self.toggle_stream)
        
        self.run_seq_btn = QPushButton("자동 분석 시퀀스 시작")
        self.run_seq_btn.setObjectName("primary")
        self.run_seq_btn.clicked.connect(self.start_sequence)
        
        right_layout.addWidget(self.stream_btn)
        right_layout.addWidget(self.run_seq_btn)
        
        # 결과 표시
        self.result_box = QGroupBox("최근 분석 결과")
        result_layout = QVBoxLayout()
        self.result_text = QLabel("결과 없음")
        self.result_text.setStyleSheet("font-size: 24px; color: #e74c3c; font-weight: bold;")
        self.result_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(self.result_text)
        self.result_box.setLayout(result_layout)
        right_layout.addWidget(self.result_box)
        
        right_layout.addStretch()
        main_layout.addLayout(right_layout, 3)

        self.last_selected_roi = None

    def toggle_stream(self):
        if self.video_thread is None or not self.video_thread.isRunning():
            self.rtsp_url = self.rtsp_input.text()
            self.video_thread = VideoThread(self.rtsp_url)
            self.video_thread.change_pixmap_signal.connect(self.update_image)
            self.video_thread.raw_frame_signal.connect(self.update_raw_frame)
            self.video_thread.start()
            self.stream_btn.setText("스트리밍 중단")
            self.status_label.setText(f"스트리밍 연결 중: {self.rtsp_url}")
        else:
            self.video_thread.stop()
            self.video_thread = None
            self.stream_btn.setText("스트리밍 시작")
            self.status_label.setText("스트리밍 중단됨")

    def update_image(self, qt_img):
        pixmap = QPixmap.fromImage(qt_img)
        p = pixmap.scaled(self.image_label.width(), self.image_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
        self.image_label.setPixmap(p)

    def update_raw_frame(self, frame):
        self.latest_frame = frame

    def on_roi_selected(self, rect):
        self.last_selected_roi = rect
        self.status_label.setText(f"영역 선택됨: {rect.x()}, {rect.y()}, {rect.width()}x{rect.height()}")

    def save_current_roi(self):
        if self.last_selected_roi is None:
            self.status_label.setText("먼저 화면에서 마우스로 영역을 드래그하세요.")
            return
        
        # 실제 영상 크기와 GUI 레이블 크기 간의 비율 보정 필요
        # (간단화를 위해 현재 표시되는 픽셀 좌표를 그대로 저장하고, 
        # SequenceManager에서 로드 시 보정하거나, 여기서 영상 좌표로 변환하여 저장)
        # 여기서는 영상 좌표로 변환하여 저장하는 로직을 간단히 구현
        
        if self.latest_frame is not None:
            h_orig, w_orig = self.latest_frame.shape[:2]
            label_w = self.image_label.width()
            label_h = self.image_label.height()
            
            # 실제 표시되는 이미지의 오프셋 및 스케일 계산 (KeepAspectRatio 대응)
            pixmap = self.image_label.pixmap()
            if pixmap:
                actual_w = pixmap.width()
                actual_h = pixmap.height()
                offset_x = (label_w - actual_w) // 2
                offset_y = (label_h - actual_h) // 2
                
                # 상대 좌표로 변환
                rel_x = (self.last_selected_roi.x() - offset_x) / actual_w
                rel_y = (self.last_selected_roi.y() - offset_y) / actual_h
                rel_w = self.last_selected_roi.width() / actual_w
                rel_h = self.last_selected_roi.height() / actual_h
                
                # 영상 절대 좌표로 변환
                abs_roi = [
                    int(rel_x * w_orig),
                    int(rel_y * h_orig),
                    int(rel_w * w_orig),
                    int(rel_h * h_orig)
                ]
                
                preset_no = str(self.current_preset_spin.value())
                rois = self.seq_manager.load_rois()
                rois[preset_no] = abs_roi
                self.seq_manager.save_rois(rois)
                
                self.status_label.setText(f"프리셋 {preset_no} ROI 저장 완료: {abs_roi}")

    def update_kakao_token(self):
        token = self.token_input.text().strip()
        if token:
            self.notifier.update_token(token)
            self.status_label.setText("카카오 토큰이 업데이트되었습니다.")
            self.token_input.clear()
        else:
            self.status_label.setText("토큰을 입력해주세요.")

    def start_sequence(self):
        try:
            presets = [int(p.strip()) for p in self.preset_input.text().split(",") if p.strip()]
        except:
            self.status_label.setText("프리셋 번호 형식이 잘못되었습니다.")
            return

        self.status_label.setText(f"자동 분석 시퀀스 시작... ({len(presets)}개 프리셋)")
        self.run_seq_btn.setEnabled(False)
        
        # 실제로는 별도 스레드에서 실행해야 GUI가 안 멈춤
        results, total = self.seq_manager.run_sequence(self.rtsp_url, presets)
        
        if results:
            self.result_text.setText(f"총 {total} 명")
            self.status_label.setText("분석 완료 및 로그 저장됨.")
            
            # 카카오톡 전송
            msg = f"[성림 인원 카운터] 분석 결과\n총 인원: {total}명\n상세: "
            msg += ", ".join([f"P{k}:{v}명" for k, v in results.items()])
            self.notifier.send_message(msg)
        else:
            self.status_label.setText("분석 실패 (스트림 연결 확인)")
            
        self.run_seq_btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AttendanceGUI()
    window.show()
    sys.exit(app.exec())

    window.show()
    sys.exit(app.exec())
