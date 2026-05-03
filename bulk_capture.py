import time
import cv2
import os
from datetime import datetime
from camera_controller import CameraController
from logger_setup import logger

def run_bulk_capture(rtsp_url, presets, save_dir="captures"):
    """
    지정된 프리셋들을 순회하며 사진을 저장합니다.
    - 각 프리셋 이동 후 4초 대기 보장
    - 캡처 시점별 개별 타임스탬프 적용
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        logger.info(f"저장 디렉토리 생성됨: {save_dir}")

    cam = CameraController("192.168.0.90", "admin", "admin")
    
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        logger.error("RTSP 스트림에 연결할 수 없습니다.")
        return

    for preset in presets:
        logger.info(f"--- 프리셋 {preset}번 작업 시작 ---")
        
        # 1. 카메라 이동 명령 전송
        success, msg = cam.move_to_preset(preset)
        if not success:
            logger.warning(f"프리셋 {preset} 이동 실패: {msg}")
            continue
            
        # 2. 이동 및 안정화를 위한 4초 완전 대기
        logger.info(f"프리셋 {preset} 이동 중... 4초간 대기합니다.")
        time.sleep(4)
        
        # 3. 최신 프레임을 가져오기 위해 충분히 버퍼 비우기 (RTSP 지연 대응)
        # 약 1~2초 분량의 프레임을 버려야 최신 화면이 나옵니다.
        for _ in range(30):
            ret, frame = cap.read()
            
        if ret:
            # 4. 저장 시점에 맞는 타임스탬프 생성
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"preset_{preset}_{current_time}.jpg"
            file_path = os.path.join(save_dir, file_name)
            
            # 5. 이미지 저장
            cv2.imwrite(file_path, frame)
            logger.info(f"[저장 완료] {file_path}")
            
            # 6. 다음 이동 전 1초 대기 (요청 사항)
            logger.info("다음 프리셋 이동 전 1초간 대기합니다.")
            time.sleep(1)
        else:
            logger.error(f"프리셋 {preset}에서 프레임을 캡처하지 못했습니다.")

        logger.info(f"--- 프리셋 {preset}번 작업 완료 ---\n")

    cap.release()
    logger.info("모든 프리셋 캡처 작업이 종료되었습니다.")

if __name__ == "__main__":
    RTSP_URL = "rtsp://mev.o-r.kr:20003/stream1"
    TARGET_PRESETS = [2, 3, 4, 5, 6, 7]
    
    logger.info(f"재작업 시작: 프리셋 {TARGET_PRESETS} (4초 대기 보장)")
    run_bulk_capture(RTSP_URL, TARGET_PRESETS)
