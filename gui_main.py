import sys
import cv2
import json
import os
import logging
from logger_setup import logger
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QGroupBox, QLineEdit, QFormLayout, QSpinBox)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from detector import PersonDetector
from sequence_manager import SequenceManager
from kakao_notifier import KakaoNotifier

class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    raw_frame_signal = pyqtSignal(object)

    def __init__(self, rtsp_url):
        super().__init__()
        self.rtsp_url = rtsp_url
        self._run_flag = True

    def run(self):
        try:
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
                    self.msleep(1000)
                    cap.open(self.rtsp_url)
            cap.release()
        except Exception as e:
            logger.error(f"VideoThread 실행 중 오류: {str(e)}", exc_info=True)

    def stop(self):
        self._run_flag = False
        self.wait()

class AnalysisThread(QThread):
    finished_signal = pyqtSignal(dict, int)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, seq_manager, rtsp_url, presets):
        super().__init__()
        self.seq_manager = seq_manager
        self.rtsp_url = rtsp_url
        self.presets = presets

    def run(self):
        try:
            self.status_signal.emit(f"분석 시퀀스 시작 (프리셋: {self.presets})...")
            results, total = self.seq_manager.run_sequence(self.rtsp_url, self.presets)
            if results:
                self.finished_signal.emit(results, total)
            else:
                self.error_signal.emit("분석 결과가 없거나 스트림 연결에 실패했습니다.")
        except Exception as e:
            logger.error(f"AnalysisThread 오류: {str(e)}", exc_info=True)
            self.error_signal.emit(str(e))

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
        try:
            logger.info("애플리케이션 초기화 시작...")
            self.detector = PersonDetector()
            self.camera_config = {
                'ip': '192.168.0.90',
                'user': 'admin',
                'password': 'admin'
            }
            self.rtsp_url = "rtsp://mev.o-r.kr:20003/stream1"
            self.presets_to_run = [1, 2]
            
            self.seq_manager = SequenceManager(self.camera_config, self.detector)
            self.notifier = KakaoNotifier()
            self.init_ui()
            
            self.video_thread = None
            self.analysis_thread = None
            self.latest_frame = None
            logger.info("애플리케이션 초기화 완료.")
        except Exception as e:
            logger.critical(f"초기화 중 치명적 오류 발생: {str(e)}", exc_info=True)
            sys.exit(1)

    def init_ui(self):
        self.setWindowTitle("성림 출석 인원 카운터 v1.1 (Stable)")
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

        left_layout = QVBoxLayout()
        self.image_label = ROIImageLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 2px solid #34495e; background-color: black;")
        self.image_label.setMinimumSize(800, 600)
        self.image_label.roi_selected.connect(self.on_roi_selected)
        left_layout.addWidget(self.image_label)

        self.status_label = QLabel("준비 완료")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.status_label)
        main_layout.addLayout(left_layout, 7)

        right_layout = QVBoxLayout()
        config_group = QGroupBox("카메라 및 프리셋 설정")
        config_form = QFormLayout()
        self.rtsp_input = QLineEdit(self.rtsp_url)
        self.preset_input = QLineEdit(", ".join(map(str, self.presets_to_run)))
        config_form.addRow("RTSP URL:", self.rtsp_input)
        config_form.addRow("분석 프리셋(쉼표 구분):", self.preset_input)
        config_group.setLayout(config_form)
        right_layout.addWidget(config_group)

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

        self.stream_btn = QPushButton("스트리밍 시작")
        self.stream_btn.setObjectName("secondary")
        self.stream_btn.clicked.connect(self.toggle_stream)
        
        self.run_seq_btn = QPushButton("자동 분석 시퀀스 시작")
        self.run_seq_btn.setObjectName("primary")
        self.run_seq_btn.clicked.connect(self.start_sequence)
        
        right_layout.addWidget(self.stream_btn)
        right_layout.addWidget(self.run_seq_btn)
        
        kakao_group = QGroupBox("카카오톡 알림 설정")
        kakao_layout = QVBoxLayout()
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("여기에 액세스 토큰 입력...")
        self.update_token_btn = QPushButton("토큰 업데이트")
        self.update_token_btn.clicked.connect(self.update_kakao_token)
        kakao_layout.addWidget(self.token_input)
        kakao_layout.addWidget(self.update_token_btn)
        kakao_group.setLayout(kakao_layout)
        right_layout.addWidget(kakao_group)

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
        try:
            if self.video_thread is None or not self.video_thread.isRunning():
                self.rtsp_url = self.rtsp_input.text()
                logger.info(f"RTSP 스트리밍 시작 시도: {self.rtsp_url}")
                self.video_thread = VideoThread(self.rtsp_url)
                self.video_thread.change_pixmap_signal.connect(self.update_image)
                self.video_thread.raw_frame_signal.connect(self.update_raw_frame)
                self.video_thread.start()
                self.stream_btn.setText("스트리밍 중단")
                self.status_label.setText(f"스트리밍 연결 중: {self.rtsp_url}")
            else:
                logger.info("RTSP 스트리밍 중단")
                self.video_thread.stop()
                self.video_thread = None
                self.stream_btn.setText("스트리밍 시작")
                self.status_label.setText("스트리밍 중단됨")
        except Exception as e:
            logger.error(f"스트리밍 전환 중 오류 발생: {str(e)}", exc_info=True)
            self.status_label.setText(f"오류: {str(e)}")

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
        try:
            if self.last_selected_roi is None:
                self.status_label.setText("먼저 화면에서 마우스로 영역을 드래그하세요.")
                return
            
            if self.latest_frame is not None:
                h_orig, w_orig = self.latest_frame.shape[:2]
                label_w = self.image_label.width()
                label_h = self.image_label.height()
                pixmap = self.image_label.pixmap()
                if pixmap:
                    actual_w = pixmap.width()
                    actual_h = pixmap.height()
                    offset_x = (label_w - actual_w) // 2
                    offset_y = (label_h - actual_h) // 2
                    rel_x = (self.last_selected_roi.x() - offset_x) / actual_w
                    rel_y = (self.last_selected_roi.y() - offset_y) / actual_h
                    rel_w = self.last_selected_roi.width() / actual_w
                    rel_h = self.last_selected_roi.height() / actual_h
                    abs_roi = [int(rel_x * w_orig), int(rel_y * h_orig), int(rel_w * w_orig), int(rel_h * h_orig)]
                    preset_no = str(self.current_preset_spin.value())
                    rois = self.seq_manager.load_rois()
                    rois[preset_no] = abs_roi
                    self.seq_manager.save_rois(rois)
                    logger.info(f"프리셋 {preset_no} ROI 저장: {abs_roi}")
                    self.status_label.setText(f"프리셋 {preset_no} ROI 저장 완료.")
        except Exception as e:
            logger.error(f"ROI 저장 중 오류: {str(e)}", exc_info=True)

    def update_kakao_token(self):
        token = self.token_input.text().strip()
        if token:
            self.notifier.update_token(token)
            logger.info("카카오 토큰 업데이트됨")
            self.status_label.setText("카카오 토큰이 업데이트되었습니다.")
            self.token_input.clear()

    def start_sequence(self):
        try:
            presets = [int(p.strip()) for p in self.preset_input.text().split(",") if p.strip()]
            self.rtsp_url = self.rtsp_input.text()
            
            self.run_seq_btn.setEnabled(False)
            self.analysis_thread = AnalysisThread(self.seq_manager, self.rtsp_url, presets)
            self.analysis_thread.finished_signal.connect(self.on_analysis_finished)
            self.analysis_thread.error_signal.connect(self.on_analysis_error)
            self.analysis_thread.status_signal.connect(lambda s: self.status_label.setText(s))
            self.analysis_thread.start()
            
        except Exception as e:
            logger.error(f"시퀀스 준비 중 오류: {str(e)}")
            self.status_label.setText("설정을 확인해주세요.")
            self.run_seq_btn.setEnabled(True)

    def on_analysis_finished(self, results, total):
        logger.info(f"분석 완료: 총 {total}명")
        self.result_text.setText(f"총 {total} 명")
        self.status_label.setText("분석 완료 및 로그 저장됨.")
        self.run_seq_btn.setEnabled(True)
        
        # 카카오톡 전송
        msg = f"[성림 인원 카운터] 분석 결과\n총 인원: {total}명\n상세: "
        msg += ", ".join([f"P{k}:{v}명" for k, v in results.items()])
        self.notifier.send_message(msg)

    def on_analysis_error(self, error_msg):
        logger.error(f"분석 시퀀스 에러: {error_msg}")
        self.status_label.setText(f"분석 오류: {error_msg}")
        self.run_seq_btn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        window = AttendanceGUI()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"어플리케이션 실행 중 오류: {str(e)}", exc_info=True)
