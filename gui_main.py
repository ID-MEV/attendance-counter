import sys
import cv2
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt
from detector import PersonDetector

class AttendanceGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.detector = PersonDetector()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("성림 인원 카운터 (Prototype)")
        self.setGeometry(100, 100, 1000, 700)

        # 메인 레이아웃
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 이미지 표시 레이블
        self.image_label = QLabel("이미지를 불러와 주세요.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 2px dashed #aaa; background-color: #f0f0f0;")
        self.image_label.setMinimumSize(800, 500)
        main_layout.addWidget(self.image_label)

        # 결과 정보 표시
        self.result_label = QLabel("탐지 결과: - 명")
        self.result_label.setStyleSheet("font-size: 20px; font-weight: bold; color: blue;")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.result_label)

        # 버튼 레이아웃
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("사진 불러오기")
        self.load_btn.clicked.connect(self.load_image)
        self.analyze_btn = QPushButton("인원 분석 시작")
        self.analyze_btn.clicked.connect(self.analyze_image)
        self.analyze_btn.setEnabled(False)

        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.analyze_btn)
        main_layout.addLayout(btn_layout)

        self.current_frame = None

    def load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "이미지 선택", "", "Image files (*.jpg *.png)")
        if file_path:
            self.current_frame = cv2.imread(file_path)
            self.display_image(self.current_frame)
            self.analyze_btn.setEnabled(True)
            self.result_label.setText("이미지 로드 완료. 분석을 시작하세요.")

    def analyze_image(self):
        if self.current_frame is not None:
            # conf_threshold를 0.15로 낮추어 아주 작은 형태도 잡도록 설정
            # iou_threshold를 0.5로 설정하여 겹쳐 있는 사람들을 분리
            count, annotated_frame, _ = self.detector.detect_people(
                self.current_frame, 
                conf_threshold=0.15, 
                iou_threshold=0.5
            )
            self.display_image(annotated_frame)
            self.result_label.setText(f"탐지 결과: {count} 명 발견!")

    def display_image(self, img):
        # OpenCV 이미지를 QImage로 변환
        rgb_image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        convert_to_Qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        # 레이블 크기에 맞춰 이미지 축소
        pixmap = QPixmap.fromImage(convert_to_Qt_format)
        p = pixmap.scaled(self.image_label.width(), self.image_label.height(), Qt.AspectRatioMode.KeepAspectRatio)
        self.image_label.setPixmap(p)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AttendanceGUI()
    window.show()
    sys.exit(app.exec())
