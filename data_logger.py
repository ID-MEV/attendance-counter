import csv
import os
from datetime import datetime

class DataLogger:
    def __init__(self, file_path='attendance_log.csv'):
        self.file_path = file_path
        self._prepare_file()

    def _prepare_file(self):
        """파일이 없으면 헤더를 포함하여 생성합니다."""
        if not os.path.exists(self.file_path):
            with open(self.file_path, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # 헤더 구성: 일시, 프리셋별 상세 결과(JSON 문자열 형태), 총합
                writer.writerow(['일시', '상세 결과(프리셋:인원)', '총 합계'])

    def log_result(self, details, total_count):
        """
        결과를 엑셀(CSV) 파일에 기록합니다.
        :param details: dict, 예: {1: 5, 2: 3} (프리셋 1번에 5명, 2번에 3명)
        :param total_count: int, 전체 합계 인원
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 상세 결과를 문자열로 변환 (예: "Preset 1: 5, Preset 2: 3")
        detail_str = ", ".join([f"프리셋 {k}: {v}명" for k, v in details.items()])
        
        try:
            with open(self.file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, detail_str, f"{total_count}명"])
            print(f"[성공] 데이터가 {self.file_path}에 기록되었습니다.")
            return True
        except Exception as e:
            print(f"[오류] 파일 기록 실패: {str(e)}")
            return False

if __name__ == "__main__":
    # 테스트 코드
    logger = DataLogger()
    test_details = {1: 12, 2: 8, 3: 5}
    logger.log_result(test_details, sum(test_details.values()))
