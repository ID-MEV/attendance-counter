import logging
import sys

def setup_logger():
    """애플리케이션 전역 로깅 설정"""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # 포맷 설정
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 파일 출력 설정
    file_handler = logging.FileHandler('app.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # 콘솔 출력 설정
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 초기화 실행
logger = setup_logger()
logger.info("로깅 시스템이 초기화되었습니다.")
