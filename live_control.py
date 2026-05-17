import sys
import cv2
import logging
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QGroupBox, QPlainTextEdit, QFormLayout, QGridLayout)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from camera_controller import CameraController
from detector import PersonDetector # PersonDetector 임포트
from logger_setup import logger

class LiveVideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    raw_frame_signal = pyqtSignal(object)
    stream_status_signal = pyqtSignal(bool, str) # 연결 상태와 메시지를 전달하는 새로운 시그널

    def __init__(self, rtsp_url):
        super().__init__()
        self.rtsp_url = rtsp_url
        self._run_flag = True
        self._cap = None # cv2.VideoCapture 객체를 명시적으로 관리
        self.is_stream_connected = False # 스트림 연결 상태 추적

    def run(self):
        while self._run_flag:
            if not self.is_stream_connected:
                logger.info(f"RTSP 스트림 연결 시도 중: {self.rtsp_url}")
                self._cap = cv2.VideoCapture(self.rtsp_url)
                if self._cap.isOpened():
                    self.is_stream_connected = True
                    self.stream_status_signal.emit(True, "스트림 연결 성공")
                    logger.info("RTSP 스트림 연결 성공.")
                else:
                    self.is_stream_connected = False
                    self.stream_status_signal.emit(False, f"RTSP 스트림을 열 수 없습니다: {self.rtsp_url}")
                    logger.warning(f"RTSP 스트림을 열 수 없습니다: {self.rtsp_url}. 5초 후 재시도.")
                    self.msleep(5000) # 스트림을 열 수 없는 경우 5초 대기 후 재시도
                    self.clean_up_cap() # 실패 시 리소스 정리
                    continue # 재시도 루프
            
            # 스트림이 연결된 경우에만 프레임을 읽습니다.
            ret, frame = self._cap.read()
            if ret:
                if frame is None: # 프레임이 비어있는지 확인
                    logger.warning("읽어온 프레임이 비어있습니다. 재시도 중...")
                    self.is_stream_connected = False
                    self.stream_status_signal.emit(False, "프레임 수신 오류. 재연결 시도 중...")
                    self.clean_up_cap()
                    self.msleep(5000)
                    continue

                self.raw_frame_signal.emit(frame)
                try:
                    logger.debug(f"읽어온 프레임 shape: {frame.shape}")
                    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # RGB 변환 다시 활성화
                    h, w, ch = rgb_image.shape # rgb_image의 shape 사용
                    bytes_per_line = rgb_image.strides[0] # rgb_image의 실제 stride 값 사용
                    
                    try: # QImage 생성 부분에 try-except 추가
                        qt_image = QImage(rgb_image.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
                        self.change_pixmap_signal.emit(qt_image.copy()) # QImage의 복사본 전달
                    except Exception as q_err:
                        logger.error(f"QImage 생성 또는 시그널 emit 중 오류 발생: {q_err}", exc_info=True)
                        self.is_stream_connected = False
                        self.stream_status_signal.emit(False, f"GUI 이미지 버퍼 오류: {q_err}")
                        self.clean_up_cap()
                        self.msleep(5000)

                except cv2.error as cv_err:
                    logger.error(f"OpenCV 이미지 처리 중 오류 발생: {cv_err} - 프레임 크기: {frame.shape if frame is not None else 'None'}", exc_info=True)
                    self.is_stream_connected = False
                    self.stream_status_signal.emit(False, f"OpenCV 오류: {cv_err}")
                    self.clean_up_cap()
                    self.msleep(5000)
                except Exception as e:
                    logger.error(f"GUI 이미지 처리 중 알 수 없는 오류 발생: {e}", exc_info=True)
                    self.is_stream_connected = False
                    self.stream_status_signal.emit(False, f"알 수 없는 오류: {e}")
                    self.clean_up_cap()
                    self.msleep(5000)
            else:
                logger.warning(f"프레임을 읽을 수 없습니다. 스트림이 끊겼거나 오류가 발생했습니다. 재연결 시도 중...")
                self.is_stream_connected = False
                self.stream_status_signal.emit(False, "스트림 끊김/오류 발생. 재연결 시도 중...") # 상태 즉시 업데이트
                self.clean_up_cap() # 이전 캡처 객체 해제
                self.msleep(5000) # Wait a bit before trying to reconnect
        
        self.clean_up_cap() # 스레드 종료 시 해제

    def clean_up_cap(self):
        if self._cap:
            self._cap.release()
            self._cap = None
            logger.info("cv2.VideoCapture 리소스 해제 완료.")

    def stop(self):
        self._run_flag = False
        self.wait()

class LiveControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        # self.camera = CameraController("192.168.0.90", "admin", "admin") # CameraController 초기화 일시 비활성화
        self.camera = None # 초기화 전까지 None으로 설정
        self.detector = PersonDetector() # PersonDetector 인스턴스화
        self.rtsp_url = "rtsp://mev.o-r.kr:20003/stream1"
        self.latest_frame = None
        self.init_ui()
        
        # 비디오 스레드 자동 시작
        self.video_thread = LiveVideoThread(self.rtsp_url)
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.raw_frame_signal.connect(self.update_raw_frame)
        self.video_thread.stream_status_signal.connect(self.update_stream_status) # 새로운 시그널 연결
        self.video_thread.start()

    def _ensure_camera_initialized(self):
        if self.camera is None:
            self.add_log("카메라 컨트롤러 초기화 시도 중...")
            try:
                # 여기에 실제 카메라 IP, 사용자 이름, 비밀번호를 입력해야 합니다.
                # 현재는 더미 값입니다. 실제 환경에 맞게 변경하세요.
                self.camera = CameraController("192.168.0.90", "admin", "admin") 
                self.add_log("카메라 컨트롤러 초기화 성공.")
                return True
            except Exception as e:
                logger.error(f"카메라 컨트롤러 초기화 중 오류 발생: {e}", exc_info=True)
                self.add_log(f"[오류] 카메라 컨트롤러 초기화 실패: {e}")
                return False
        return True # 이미 초기화되어 있으면 True 반환

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
        
        self.reconnect_btn = QPushButton("스트림 재연결 시도")
        self.reconnect_btn.setStyleSheet("background-color: #e67e22;")
        self.reconnect_btn.clicked.connect(self.reconnect_stream)
        left_layout.addWidget(self.reconnect_btn)
        
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

        # 1.5. 연속 카메라 제어 섹션
        continuous_move_group = QGroupBox("연속 카메라 제어")
        continuous_layout = QVBoxLayout()
        
        # 방향 제어 버튼 (그리드 레이아웃)
        direction_layout = QGridLayout()
        self.up_btn = QPushButton("▲ Up")
        self.down_btn = QPushButton("▼ Down")
        self.left_btn = QPushButton("◀ Left")
        self.right_btn = QPushButton("▶ Right")
        self.zoom_in_btn = QPushButton("Zoom +")
        self.zoom_out_btn = QPushButton("Zoom -")

        direction_layout.addWidget(self.up_btn, 0, 1)
        direction_layout.addWidget(self.left_btn, 1, 0)
        direction_layout.addWidget(self.right_btn, 1, 2)
        direction_layout.addWidget(self.down_btn, 2, 1)
        
        # 줌 버튼은 별도로 추가
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(self.zoom_in_btn)
        zoom_layout.addWidget(self.zoom_out_btn)

        self.up_btn.pressed.connect(lambda: self.start_continuous_move("up", 10, 10))
        self.up_btn.released.connect(lambda: self.stop_continuous_move("move")) # "move" 타입 추가
        self.down_btn.pressed.connect(lambda: self.start_continuous_move("down", 10, 10))
        self.down_btn.released.connect(lambda: self.stop_continuous_move("move")) # "move" 타입 추가
        self.left_btn.pressed.connect(lambda: self.start_continuous_move("left", 10, 10))
        self.left_btn.released.connect(lambda: self.stop_continuous_move("move")) # "move" 타입 추가
        self.right_btn.pressed.connect(lambda: self.start_continuous_move("right", 10, 10))
        self.right_btn.released.connect(lambda: self.stop_continuous_move("move")) # "move" 타입 추가
        self.zoom_in_btn.pressed.connect(lambda: self.start_continuous_move("zoomin", 5, 5))
        self.zoom_in_btn.released.connect(lambda: self.stop_continuous_move("zoom")) # "zoom" 타입 추가
        self.zoom_out_btn.pressed.connect(lambda: self.start_continuous_move("zoomout", 5, 5))
        self.zoom_out_btn.released.connect(lambda: self.stop_continuous_move("zoom")) # "zoom" 타입 추가

        continuous_layout.addLayout(direction_layout)
        continuous_layout.addLayout(zoom_layout)
        continuous_move_group.setLayout(continuous_layout)
        right_layout.addWidget(continuous_move_group)

        # 새로운 버튼 추가
        self.analyze_button = QPushButton("사람수 세기 분석")
        self.analyze_button.setStyleSheet("background-color: #2ecc71; color: white;")
        self.analyze_button.clicked.connect(self.analyze_current_frame_for_people) # 버튼 연결
        right_layout.addWidget(self.analyze_button)
        
        self.person_count_label = QLabel("인원수: 0명") # 인원수 표시 라벨
        self.person_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.person_count_label.setStyleSheet("font-size: 18px; color: #f1c40f; font-weight: bold; margin-top: 10px;")
        right_layout.addWidget(self.person_count_label)
        
        self.key_status_label = QLabel("키 입력: 없음") # 키 입력 상태 표시 라벨
        self.key_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_status_label.setStyleSheet("background-color: #7f8c8d; color: white; font-weight: bold; padding: 5px; border-radius: 3px; margin-top: 5px;")
        right_layout.addWidget(self.key_status_label)

        # 2. 작업 로그 섹션
        log_group = QGroupBox("작업 로그")
        log_layout = QVBoxLayout()
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFixedHeight(70) # 3줄 정도 높이로 제한
        log_layout.addWidget(self.log_display)
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group) # 높이를 제한했으므로 stretch는 제거

        main_layout.addLayout(right_layout, 3)

        self.add_log("라이브 컨트롤러가 시작되었습니다.")

    def reconnect_stream(self):
        self.add_log("스트림 재연결 시도 중...")
        self.video_label.setText("스트림 재연결 중...")
        
        # 기존 스레드 중지
        if self.video_thread and self.video_thread.isRunning():
            self.video_thread.stop()
            self.video_thread.quit() # 스레드의 이벤트 루프를 종료
            self.video_thread.wait() # 스레드가 완전히 종료될 때까지 대기
            self.add_log("기존 스트림 스레드 중지 완료.")
            self.video_thread = None # 이전 스레드 참조를 해제하여 가비지 컬렉션 허용
            QThread.msleep(500) # 리소스 해제를 위한 짧은 지연
            self.add_log("새 LiveVideoThread 생성 시도...")
            
        # 새로운 스레드 시작
        self.video_thread = LiveVideoThread(self.rtsp_url)
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.raw_frame_signal.connect(self.update_raw_frame)
        self.add_log("새 LiveVideoThread 시작 시도...")
        self.video_thread.start()
        self.add_log("새로운 스트림 스레드 시작 완료.")

    def update_stream_status(self, is_connected, message):
        self.add_log(message)
        if is_connected:
            self.video_label.setText("") # 영상이 정상적으로 표시될 것이므로 텍스트 제거
            self.video_label.setStyleSheet("background-color: black; border: 2px solid #34495e;")
        else:
            self.video_label.setText(message)
            self.video_label.setStyleSheet("background-color: #e74c3c; color: white; border: 2px solid #c0392b;") # 에러 상태 표시

    def update_image(self, qt_img):
        try:
            pixmap = QPixmap.fromImage(qt_img)
            p = pixmap.scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
            self.video_label.setPixmap(p) # 이미지 표시 주석 해제
        except Exception as e:
            logger.error(f"GUI video_label 업데이트 중 오류 발생: {e}", exc_info=True)
            self.add_log(f"[오류] GUI 영상 표시 오류: {e}")
            self.video_label.setText(f"GUI 영상 표시 오류: {e}")
            self.video_label.setStyleSheet("background-color: #e74c3c; color: white; border: 2px solid #c0392b;")

    def update_raw_frame(self, frame):
        self.latest_frame = frame

    def capture_snapshot(self):
        if not self._ensure_camera_initialized():
            return
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

    def analyze_current_frame_for_people(self):
        self.add_log("현재 화면 사람 수 분석 시작...")
        if self.latest_frame is None:
            self.add_log("[오류] 분석할 프레임이 없습니다. 스트림이 연결되어 있는지 확인하세요.")
            self.person_count_label.setText("인원수: 오류")
            return
        
        try:
            # 사람 감지 실행
            # GUI의 video_label에 표시되는 이미지는 원본 프레임이 아닐 수 있으므로,
            # raw_frame_signal을 통해 받은 self.latest_frame을 사용해야 함.
            count, annotated_frame, _ = self.detector.detect_people(self.latest_frame)
            
            self.person_count_label.setText(f"인원수: {count}명")
            self.add_log(f"[분석 완료] 현재 화면에서 {count}명 발견")
            
            # 탐지 결과를 시각화하여 video_label에 일시적으로 표시 (선택 사항)
            # GUI의 video_label 크기에 맞게 annotated_frame을 스케일링하여 표시
            h, w, ch = annotated_frame.shape
            bytes_per_line = ch * w
            qt_image = QImage(annotated_frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888) # BGR888로 변경
            pixmap = QPixmap.fromImage(qt_image)
            p = pixmap.scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
            self.video_label.setPixmap(p) # 이미지 표시

            # 일정 시간 후 원본 스트림으로 되돌리기 (선택 사항, 복잡도 증가)
            # 여기서는 분석된 프레임을 즉시 표시하고, 다음 스트림 프레임이 오면 덮어쓰도록 합니다.

        except Exception as e:
            logger.error(f"사람 수 분석 중 오류 발생: {str(e)}", exc_info=True)
            self.add_log(f"[오류] 사람 수 분석 실패: {str(e)}")
            self.person_count_label.setText("인원수: 오류")

    def move_to_preset(self):
        if not self._ensure_camera_initialized():
            return
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

    def start_continuous_move(self, direction, speed_param1=10, speed_param2=10):
        if not self._ensure_camera_initialized():
            return
        self.add_log(f"명령: 카메라 {direction} 방향으로 연속 이동 시작...")
        success, msg = self.camera.move_continuous(direction, speed_param1, speed_param2)
        if success:
            self.add_log(f"[성공] 카메라 {direction} 이동 시작")
        else:
            self.add_log(f"[실패] {msg}")

    def stop_continuous_move(self, command_type="move"): # command_type 인자 추가
        if not self._ensure_camera_initialized():
            return
        self.add_log("명령: 카메라 움직임 중지...")
        success, msg = self.camera.stop_movement(command_type) # command_type 전달
        if success:
            self.add_log("[성공] 카메라 움직임 중지")
        else:
            self.add_log(f"[실패] {msg}")

    def add_log(self, text):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_display.appendPlainText(f"[{now}] {text}")
        try:
            # Explicitly encode and decode to handle potential encoding issues
            encoded_text = text.encode('utf-8', errors='replace').decode('utf-8')
            logger.info(f"UI Log: {encoded_text}")
        except Exception as e:
            logger.error(f"Error logging UI message: {e} - Original text: {text}")

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        
        key = event.key()
        key_text = event.text().lower()
        self.key_status_label.setText(f"키 입력: {key_text.upper()}")
        
        # 숫자 입력 (프리셋 번호 설정)
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self.preset_input.setText(str(key - Qt.Key.Key_0))
            self.add_log(f"프리셋 번호 입력: {key - Qt.Key.Key_0}")
            return # 숫자 키는 여기서 처리 완료

        if key == Qt.Key.Key_Space:
            self.add_log("스페이스바 누름: 프리셋 이동 시도")
            self.move_to_preset()
        elif key_text == 'w':
            self.start_continuous_move("up", 10, 10)
        elif key_text == 's':
            self.start_continuous_move("down", 10, 10)
        elif key_text == 'a':
            self.start_continuous_move("left", 10, 10)
        elif key_text == 'd':
            self.start_continuous_move("right", 10, 10)
        elif key_text == 'q':
            self.start_continuous_move("zoomin", 5, 5)
        elif key_text == 'e':
            self.start_continuous_move("zoomout", 5, 5)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            return

        key_text = event.text().lower()
        self.key_status_label.setText("키 입력: 없음") # 키 떼면 상태 초기화
        
        if key_text in ['w', 's', 'a', 'd']:
            self.stop_continuous_move("move")
        elif key_text in ['q', 'e']:
            self.stop_continuous_move("zoom")
        else:
            super().keyReleaseEvent(event)

    def closeEvent(self, event):
        self.video_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LiveControlGUI()
    window.show()
    sys.exit(app.exec())
