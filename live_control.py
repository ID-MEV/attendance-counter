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
from detector import PersonDetector
from logger_setup import logger

class LiveVideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage, int)
    raw_frame_signal = pyqtSignal(object, int)
    stream_status_signal = pyqtSignal(bool, str, int)

    def __init__(self, rtsp_url, camera_id):
        super().__init__()
        self.rtsp_url = rtsp_url
        self.camera_id = camera_id
        self._run_flag = True
        self._cap = None
        self.is_stream_connected = False

    def run(self):
        logger.info(f"스레드 시작 ({self.camera_id}번): {self.rtsp_url}")
        while self._run_flag:
            if not self.is_stream_connected:
                self._cap = cv2.VideoCapture(self.rtsp_url)
                if self._cap.isOpened():
                    self.is_stream_connected = True
                    self.stream_status_signal.emit(True, f"연결 성공: {self.rtsp_url}", self.camera_id)
                else:
                    self.is_stream_connected = False
                    self.stream_status_signal.emit(False, f"연결 실패: {self.rtsp_url}", self.camera_id)
                    # 자동 재연결 방지: 실패 시 루프 종료
                    break 
            
            ret, frame = self._cap.read()
            if ret and frame is not None:
                self.raw_frame_signal.emit(frame, self.camera_id)
                try:
                    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = rgb_image.strides[0]
                    qt_image = QImage(rgb_image.tobytes(), w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    self.change_pixmap_signal.emit(qt_image.copy(), self.camera_id)
                except Exception as e:
                    logger.error(f"이미지 변환 에러 ({self.camera_id}번): {e}")
            else:
                self.is_stream_connected = False
                self.stream_status_signal.emit(False, "스트림 끊김.", self.camera_id)
                break
        
        if self._cap:
            self._cap.release()
            self._cap = None

    def stop(self):
        self._run_flag = False
        self.wait()

class LiveControlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.camera = None
        self.detector = PersonDetector()
        
        # 카메라 주소 설정
        self.camera_urls = {
            1: "rtsp://mev.o-r.kr:20001/stream1",
            2: "rtsp://mev.o-r.kr:20002/stream1",
            3: "rtsp://mev.o-r.kr:20003/stream1"
        }
        self.current_main_camera = 3  # 기본 메인 카메라는 3번
        self.rtsp_url = self.camera_urls[self.current_main_camera]
        self.pending_camera_no = None
        self.latest_frame = None
        
        self.video_threads = {}
        self.init_ui()
        self.start_stream()

    def init_ui(self):
        self.setWindowTitle("성림 카메라 라이브 컨트롤러")
        self.setGeometry(100, 100, 1200, 850)
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

        # --- 왼쪽: 실시간 영상 영역 ---
        left_layout = QVBoxLayout()
        left_layout.setSpacing(5)
        
        self.current_url_label = QLabel(f"현재 스트림: {self.rtsp_url} (메인: {self.current_main_camera}번)")
        self.current_url_label.setStyleSheet("color: #f1c40f; font-size: 14px; font-weight: bold; margin: 0px; padding: 0px;")
        self.current_url_label.setFixedHeight(25)
        left_layout.addWidget(self.current_url_label)
        
        # 메인 큰 화면
        self.video_label = QLabel("영상 연결 시도 중...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; border: 2px solid #34495e;")
        self.video_label.setMinimumSize(800, 420)
        left_layout.addWidget(self.video_label)
        
        # 하단 서브 비디오(3개 멀티채널) 영역
        sub_videos_layout = QHBoxLayout()
        for i in [1, 2, 3]:
            sub_label = QLabel(f"{i}번 카메라 대기 중...")
            sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_label.setStyleSheet("background-color: black; border: 2px solid #34495e; color: #95a5a6; font-size: 11px;")
            sub_label.setFixedSize(260, 150)
            sub_videos_layout.addWidget(sub_label)
            setattr(self, f"sub_video_{i}", sub_label)
            
        left_layout.addLayout(sub_videos_layout)
        
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("모든 스트림 연결 시작")
        self.start_btn.setStyleSheet("background-color: #e67e22;")
        self.start_btn.clicked.connect(self.start_stream)
        self.start_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.stop_btn = QPushButton("모든 스트림 연결 해제")
        self.stop_btn.setStyleSheet("background-color: #c0392b;")
        self.stop_btn.clicked.connect(self.stop_stream)
        self.stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)
        
        main_layout.addLayout(left_layout, 7)

        # --- 오른쪽: 컨트롤 패널 영역 ---
        right_layout = QVBoxLayout()

        # 1. 프리셋 이동 및 스냅샷
        move_group = QGroupBox("카메라 제어")
        move_lay = QFormLayout()
        self.preset_input = QLineEdit()
        self.preset_input.setPlaceholderText("번호 입력 (m,,. jkl uio 활용)")
        self.preset_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.move_btn = QPushButton("프리셋 이동 (Enter)")
        self.move_btn.clicked.connect(self.move_to_preset)
        self.move_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        self.capture_btn = QPushButton("스냅샷 저장 (C)")
        self.capture_btn.setStyleSheet("background-color: #27ae60;")
        self.capture_btn.clicked.connect(self.capture_snapshot)
        self.capture_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        move_lay.addRow("프리셋 번호:", self.preset_input)
        move_lay.addWidget(self.move_btn)
        move_lay.addWidget(self.capture_btn)
        move_group.setLayout(move_lay)
        right_layout.addWidget(move_group)

        # 2. 연속 이동 제어 (WASD)
        cont_group = QGroupBox("연속 카메라 제어 (WASD/QE)")
        cont_lay = QVBoxLayout()
        dir_lay = QGridLayout()
        self.up_btn = QPushButton("▲ Up")
        self.down_btn = QPushButton("▼ Down")
        self.left_btn = QPushButton("◀ Left")
        self.right_btn = QPushButton("▶ Right")
        dir_lay.addWidget(self.up_btn, 0, 1)
        dir_lay.addWidget(self.left_btn, 1, 0)
        dir_lay.addWidget(self.right_btn, 1, 2)
        dir_lay.addWidget(self.down_btn, 2, 1)
        
        zoom_lay = QHBoxLayout()
        self.zoom_in_btn = QPushButton("Zoom +")
        self.zoom_out_btn = QPushButton("Zoom -")
        zoom_lay.addWidget(self.zoom_in_btn)
        zoom_lay.addWidget(self.zoom_out_btn)
        
        # 버튼 포커스 해제
        for b in [self.up_btn, self.down_btn, self.left_btn, self.right_btn, self.zoom_in_btn, self.zoom_out_btn]:
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            
        cont_lay.addLayout(dir_lay)
        cont_lay.addLayout(zoom_lay)
        cont_group.setLayout(cont_lay)
        right_layout.addWidget(cont_group)

        # 3. 분석 및 상태
        self.analyze_btn = QPushButton("사람수 세기 분석 (F)")
        self.analyze_btn.setStyleSheet("background-color: #2ecc71;")
        self.analyze_btn.clicked.connect(self.analyze_current_frame_for_people)
        self.analyze_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        right_layout.addWidget(self.analyze_btn)
        
        self.person_count_label = QLabel("인원수: 0명")
        self.person_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.person_count_label.setStyleSheet("font-size: 18px; color: #f1c40f; font-weight: bold;")
        right_layout.addWidget(self.person_count_label)
        
        self.key_status_label = QLabel("키 입력: 없음")
        self.key_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_status_label.setStyleSheet("background-color: #7f8c8d; padding: 5px; border-radius: 3px;")
        right_layout.addWidget(self.key_status_label)

        # 4. 작업 로그
        log_group = QGroupBox("작업 로그")
        log_lay = QVBoxLayout()
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFixedHeight(300)
        self.log_display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_lay.addWidget(self.log_display)
        log_group.setLayout(log_lay)
        right_layout.addWidget(log_group)

        main_layout.addLayout(right_layout, 3)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.add_log("라이브 컨트롤러가 시작되었습니다.")

    def start_stream(self):
        self.stop_stream()
        self.add_log("모든 카메라 스트림 연결 시도 중...")
        self.current_url_label.setText(f"현재 스트림: {self.camera_urls[self.current_main_camera]} (메인: {self.current_main_camera}번)")
        
        for cam_no, url in self.camera_urls.items():
            self.add_log(f"-> {cam_no}번 카메라 연결 시작: {url}")
            thread = LiveVideoThread(url, cam_no)
            thread.change_pixmap_signal.connect(self.update_image)
            thread.raw_frame_signal.connect(self.update_raw_frame)
            thread.stream_status_signal.connect(self.update_stream_status)
            thread.start()
            self.video_threads[cam_no] = thread

    def stop_stream(self):
        if self.video_threads:
            self.add_log("모든 스트림 연결을 해제하는 중...")
            for cam_no, thread in list(self.video_threads.items()):
                if thread.isRunning():
                    thread.stop()
            self.video_threads.clear()
            self.add_log("모든 스트림 연결이 중지되었습니다.")

    def update_stream_status(self, ok, msg, camera_id):
        self.add_log(f"[{camera_id}번 카메라] {msg}")
        sub_video = getattr(self, f"sub_video_{camera_id}")
        if not ok:
            sub_video.setText(f"{camera_id}번 카메라 연결 실패")
            sub_video.setStyleSheet("background-color: #c0392b; color: white; border: 2px solid #7f8c8d; font-size: 11px;")
            if camera_id == self.current_main_camera:
                self.video_label.setText(f"메인({camera_id}번) 카메라 연결 실패")
                self.video_label.setStyleSheet("background-color: #c0392b; color: white; border: 2px solid #34495e;")
        else:
            is_pending = (camera_id == self.pending_camera_no)
            border_style = "3px solid #2ecc71" if is_pending else "2px solid #34495e"
            sub_video.setStyleSheet(f"background-color: black; border: {border_style};")
            if camera_id == self.current_main_camera:
                self.video_label.setStyleSheet("background-color: black; border: 2px solid #34495e;")

    def update_image(self, img, camera_id):
        # 1. 해당 카메라의 서브 비디오 QLabel에 이미지 렌더링
        sub_video = getattr(self, f"sub_video_{camera_id}")
        sub_p = QPixmap.fromImage(img).scaled(sub_video.width(), sub_video.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        sub_video.setPixmap(sub_p)

        # 2. 현재 메인 카메라라면 큰 화면(video_label)에도 렌더링
        if camera_id == self.current_main_camera:
            p = QPixmap.fromImage(img).scaled(self.video_label.width(), self.video_label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.video_label.setPixmap(p)

    def update_raw_frame(self, frame, camera_id):
        if camera_id == self.current_main_camera:
            self.latest_frame = frame

    def add_log(self, txt):
        self.log_display.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {txt}")
        logger.info(f"UI Log: {txt}")

    def capture_snapshot(self):
        if self.latest_frame is not None:
            save_dir = "captures"
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
            cv2.imwrite(path, self.latest_frame)
            self.add_log(f"스냅샷 저장 완료: {path}")
        else:
            self.add_log("[오류] 캡처할 프레임이 없습니다.")

    def analyze_current_frame_for_people(self):
        if self.latest_frame is not None:
            count, _, _ = self.detector.detect_people(self.latest_frame)
            self.person_count_label.setText(f"인원수: {count}명")
            self.add_log(f"인원 분석 결과: {count}명 발견")
        else:
            self.add_log("[오류] 분석할 프레임이 없습니다.")

    def move_to_preset(self):
        val = self.preset_input.text().strip()
        if val.isdigit():
            self.add_log(f"명령: 프리셋 {val}번 이동 시도")
            if self._ensure_camera_initialized():
                self.camera.move_to_preset(int(val))

    def _ensure_camera_initialized(self):
        if self.camera is None:
            try:
                self.camera = CameraController("192.168.0.90", "admin", "admin")
                return True
            except Exception as e:
                self.add_log(f"카메라 컨트롤러 연결 실패: {e}")
                return False
        return True

    def start_continuous_move(self, direction, s1=10, s2=10):
        if self._ensure_camera_initialized():
            self.camera.move_continuous(direction, s1, s2)

    def stop_continuous_move(self, cmd="move"):
        if self._ensure_camera_initialized():
            self.camera.stop_movement(cmd)

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        key = event.key()
        text = event.text().lower()

        # 1. 메인 화면 전환 확정 (Space)
        if key == Qt.Key.Key_Space:
            if self.pending_camera_no is not None:
                self.current_main_camera = self.pending_camera_no
                self.rtsp_url = self.camera_urls[self.current_main_camera]
                self.add_log(f"확정: {self.current_main_camera}번 카메라를 메인 화면으로 설정")
                self.current_url_label.setText(f"현재 스트림: {self.rtsp_url} (메인: {self.current_main_camera}번)")
                
                # 대기 상태 해제 및 모든 서브 비디오 테두리를 기본 테두리로 복원
                self.pending_camera_no = None
                self.key_status_label.setText("키 입력: 없음")
                for i in [1, 2, 3]:
                    sub_video = getattr(self, f"sub_video_{i}")
                    thread = self.video_threads.get(i)
                    is_connected = thread and thread.is_stream_connected
                    if is_connected:
                        sub_video.setStyleSheet("background-color: black; border: 2px solid #34495e;")
                    else:
                        sub_video.setStyleSheet("background-color: #c0392b; color: white; border: 2px solid #7f8c8d; font-size: 11px;")
                return
            else:
                self.add_log("대기 선택된 카메라가 없습니다. 숫자 1, 2, 3을 눌러 먼저 선택하세요.")
                return

        # 2. 카메라 대기 선택 트리거 (상단 숫자키 1, 2, 3)
        if key in [Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3]:
            cam_map = {Qt.Key.Key_1: 1, Qt.Key.Key_2: 2, Qt.Key.Key_3: 3}
            target_no = cam_map[key]
            self.pending_camera_no = target_no
            self.add_log(f"{target_no}번 카메라 선택 대기 중 (Space바를 누르면 메인 화면으로 전환됩니다)")
            self.key_status_label.setText(f"{target_no}번 대기 중")
            
            # 서브 비디오 테두리 스타일 업데이트
            for i in [1, 2, 3]:
                sub_video = getattr(self, f"sub_video_{i}")
                thread = self.video_threads.get(i)
                is_connected = thread and thread.is_stream_connected
                
                if i == target_no:
                    sub_video.setStyleSheet("background-color: black; border: 3px solid #2ecc71;")
                else:
                    if is_connected:
                        sub_video.setStyleSheet("background-color: black; border: 2px solid #34495e;")
                    else:
                        sub_video.setStyleSheet("background-color: #c0392b; color: white; border: 2px solid #7f8c8d; font-size: 11px;")
            return

        # 3. 프리셋 숫자 패드 (m,,. jkl uio ;)
        p_map = {Qt.Key.Key_M:'1', Qt.Key.Key_Comma:'2', Qt.Key.Key_Period:'3',
                 Qt.Key.Key_J:'4', Qt.Key.Key_K:'5', Qt.Key.Key_L:'6',
                 Qt.Key.Key_U:'7', Qt.Key.Key_I:'8', Qt.Key.Key_O:'9', Qt.Key.Key_Semicolon:'0'}
        k_map = {'ㅡ':'1','ㅓ':'4','ㅏ':'5','ㅣ':'6','ㅕ':'7','ㅑ':'8','ㅐ':'9',';':'0'}
        
        digit = p_map.get(key) or k_map.get(text)
        if text == ',': digit = '2'
        elif text == '.': digit = '3'
        
        if digit:
            self.preset_input.setText(self.preset_input.text() + digit)
            self.key_status_label.setText(f"입력: {digit}")
            return

        # 4. 기능 키 (WASD, QE, F, C 등)
        if key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]: 
            self.move_to_preset(); self.preset_input.clear()
        elif key == Qt.Key.Key_F or text == 'ㄹ': 
            self.key_status_label.setText("F (분석)"); self.analyze_current_frame_for_people()
        elif key == Qt.Key.Key_C or text == 'ㅊ': 
            self.key_status_label.setText("C (스냅샷)"); self.capture_snapshot()
        elif key == Qt.Key.Key_W or text == 'ㅈ': 
            self.key_status_label.setText("W (Up)"); self.start_continuous_move("up")
        elif key == Qt.Key.Key_S or text == 'ㄴ': 
            self.key_status_label.setText("S (Down)"); self.start_continuous_move("down")
        elif key == Qt.Key.Key_A or text == 'ㅁ': 
            self.key_status_label.setText("A (Left)"); self.start_continuous_move("left")
        elif key == Qt.Key.Key_D or text == 'ㅇ': 
            self.key_status_label.setText("D (Right)"); self.start_continuous_move("right")
        elif key == Qt.Key.Key_Q or text == 'ㅂ': 
            self.key_status_label.setText("Q (Zoom+)"); self.start_continuous_move("zoomin", 5, 5)
        elif key == Qt.Key.Key_E or text == 'ㄷ': 
            self.key_status_label.setText("E (Zoom-)"); self.start_continuous_move("zoomout", 5, 5)
        elif key == Qt.Key.Key_Backspace: 
            self.preset_input.setText(self.preset_input.text()[:-1])
        elif key == Qt.Key.Key_Escape: 
            self.preset_input.clear()
            self.pending_camera_no = None
            self.key_status_label.setText("키 입력: 없음")
            self.add_log("입력 및 선택 초기화")
            for i in [1, 2, 3]:
                sub_video = getattr(self, f"sub_video_{i}")
                thread = self.video_threads.get(i)
                if thread and thread.is_stream_connected:
                    sub_video.setStyleSheet("background-color: black; border: 2px solid #34495e;")
                else:
                    sub_video.setStyleSheet("background-color: #c0392b; color: white; border: 2px solid #7f8c8d; font-size: 11px;")

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        key = event.key()
        text = event.text().lower()
        self.key_status_label.setText("키 입력: 없음")
        if key in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D] or text in ['ㅈ','ㄴ','ㅁ','ㅇ']:
            self.stop_continuous_move("move")
        elif key in [Qt.Key.Key_Q, Qt.Key.Key_E] or text in ['ㅂ','ㄷ']:
            self.stop_continuous_move("zoom")

    def closeEvent(self, event):
        self.stop_stream()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LiveControlGUI()
    window.show()
    sys.exit(app.exec())
