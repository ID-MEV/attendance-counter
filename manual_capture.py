import cv2
import os
import time
from datetime import datetime
from logger_setup import logger

def run_manual_capture(rtsp_url, presets, save_dir="captures"):
    """
    사용자가 직접 카메라를 이동시킨 후, 
    명령을 주면 해당 시점의 프레임을 저장합니다.
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        logger.info(f"저장 디렉토리 생성됨: {save_dir}")

    # RTSP 스트림 연결
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        logger.error("RTSP 스트림에 연결할 수 없습니다.")
        return

    print("\n" + "="*50)
    print(" [수동 캡처 모드] ")
    print(" 카메라 이동은 직접 하시고, 완료되면 Enter를 눌러주세요.")
    print("="*50 + "\n")

    for preset in presets:
        # 사용자 입력 대기
        input(f"▶ 프리셋 [{preset}]번으로 카메라를 이동시킨 후 [Enter]를 누르세요...")
        
        # 캡처 직전 버퍼 비우기 (RTSP 지연 방지)
        logger.info(f"프리셋 {preset} 캡처 준비 중 (버퍼 비우기)...")
        for _ in range(30):
            cap.read()
        
        ret, frame = cap.read()
        
        if ret:
            current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"manual_preset_{preset}_{current_time}.jpg"
            file_path = os.path.join(save_dir, file_name)
            
            # 이미지 저장
            cv2.imwrite(file_path, frame)
            print(f"  [성공] 프리셋 {preset} 저장 완료: {file_path}")
            logger.info(f"수동 저장 성공: {file_path}")
        else:
            print(f"  [오류] 프리셋 {preset} 프레임을 가져오지 못했습니다.")
            logger.error(f"수동 저장 실패: 프리셋 {preset}")

    cap.release()
    print("\n" + "="*50)
    print(" 모든 프리셋 촬영 작업이 종료되었습니다.")
    print("="*50)

if __name__ == "__main__":
    RTSP_URL = "rtsp://mev.o-r.kr:20003/stream1"
    TARGET_PRESETS = [2, 3, 4, 5, 6, 7]
    
    run_manual_capture(RTSP_URL, TARGET_PRESETS)
