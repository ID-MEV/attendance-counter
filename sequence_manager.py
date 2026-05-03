import time
import cv2
import json
import os
from camera_controller import CameraController
from detector import PersonDetector
from data_logger import DataLogger

class SequenceManager:
    def __init__(self, camera_config, detector=None, logger=None, roi_config_path='roi_config.json'):
        """
        :param camera_config: dict, {'ip': ..., 'user': ..., 'password': ...}
        :param detector: PersonDetector instance
        :param logger: DataLogger instance
        :param roi_config_path: ROI 설정 파일 경로
        """
        self.camera = CameraController(
            camera_config['ip'], 
            camera_config['user'], 
            camera_config['password']
        )
        self.detector = detector if detector else PersonDetector()
        self.logger = logger if logger else DataLogger()
        self.roi_config_path = roi_config_path
        self.rois = self.load_rois()

    def load_rois(self):
        """ROI 설정을 파일에서 불러옵니다."""
        if os.path.exists(self.roi_config_path):
            with open(self.roi_config_path, 'r') as f:
                return json.load(f)
        return {}

    def save_rois(self, rois):
        """ROI 설정을 파일에 저장합니다."""
        self.rois = rois
        with open(self.roi_config_path, 'w') as f:
            json.dump(rois, f, indent=4)

    def run_sequence(self, rtsp_url, presets):
        """
        지정된 프리셋들을 순회하며 인원을 집계합니다.
        :param rtsp_url: RTSP 스트림 주소
        :param presets: list of int, 순회할 프리셋 번호들
        :return: dict (상세 결과), int (총합)
        """
        results = {}
        total_count = 0
        
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            print("[오류] RTSP 스트림에 연결할 수 없습니다.")
            return None, 0

        for preset in presets:
            print(f">>> 프리셋 {preset}번 작업 시작...")
            
            # 1. 카메라 이동
            success, msg = self.camera.move_to_preset(preset)
            if not success:
                print(f"[경고] 프리셋 {preset} 이동 실패: {msg}")
                continue
            
            # 2. 이동 대기 (카메라 안정화)
            time.sleep(3)
            
            # 3. 프레임 캡처 (버퍼 비우기를 위해 여러 번 읽음)
            for _ in range(5):
                ret, frame = cap.read()
            
            if not ret:
                print(f"[오류] 프리셋 {preset}에서 프레임을 가져올 수 없습니다.")
                continue

            # 4. ROI 적용
            roi = self.rois.get(str(preset))
            working_frame = frame.copy()
            
            if roi:
                # roi format: [x, y, w, h]
                x, y, w, h = roi
                # ROI 영역 외를 검게 칠하거나 ROI 부분만 크롭하여 분석 가능
                # 여기서는 ROI 부분만 잘라서 분석하는 방식을 사용 (좌표 보정 필요)
                roi_frame = frame[y:y+h, x:x+w]
                count, _, _ = self.detector.detect_people(roi_frame)
            else:
                # ROI가 없으면 전체 화면 분석
                count, _, _ = self.detector.detect_people(working_frame)

            results[preset] = count
            total_count += count
            print(f"--- 프리셋 {preset} 결과: {count}명")

        cap.release()
        
        # 5. 로그 기록
        if results:
            self.logger.log_result(results, total_count)
            
        return results, total_count

if __name__ == "__main__":
    # 테스트용 설정
    cam_cfg = {
        'ip': '192.168.0.90',
        'user': 'admin',
        'password': 'admin'
    }
    rtsp = "rtsp://mev.o-r.kr:20003/stream1"
    
    manager = SequenceManager(cam_cfg)
    # 프리셋 1, 2번 순회 테스트
    res, total = manager.run_sequence(rtsp, [1, 2])
    print(f"\n최종 결과: 총 {total}명")
