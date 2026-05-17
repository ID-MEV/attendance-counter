import cv2
import sys
import logging
import os

# 기본적인 로깅 설정 (파일 출력용)
log_file = 'rtsp_test.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

rtsp_url = "rtsp://mev.o-r.kr:20003/stream1"

logger.info(f"RTSP 스트림 테스트 시작: {rtsp_url}")

cap = cv2.VideoCapture(rtsp_url)

if not cap.isOpened():
    logger.error(f"오류: RTSP 스트림을 열 수 없습니다. URL을 확인하거나 코덱/네트워크 문제를 점검하세요.")
else:
    logger.info("RTSP 스트림 열기 성공. 첫 번째 프레임을 읽어봅니다...")
    ret, frame = cap.read()
    if ret:
        logger.info(f"첫 번째 프레임 읽기 성공. 프레임 크기: {frame.shape}")
    else:
        logger.error("오류: 첫 번째 프레임을 읽을 수 없습니다.")
    cap.release()
    logger.info("RTSP 스트림 테스트 완료. 연결을 해제했습니다.")

sys.exit(0)
