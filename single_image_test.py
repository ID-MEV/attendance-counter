import cv2
import sys
import os
from detector import PersonDetector

def analyze_single_image(image_path):
    # 1. 파일 존재 확인
    if not os.path.exists(image_path):
        print(f"[오류] 파일을 찾을 수 없습니다: {image_path}")
        return

    # 2. 탐지기 초기화 (최적화된 감도 설정 사용)
    print("탐지기 로드 중...")
    detector = PersonDetector()
    
    # 3. 이미지 읽기
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"[오류] 이미지를 불러올 수 없습니다: {image_path}")
        return

    # 4. 사람 탐지 실행 (신뢰도 0.1, IOU 0.6 적용)
    print(f"분석 시작: {image_path}")
    count, annotated_frame, boxes = detector.detect_people(frame, conf_threshold=0.1, iou_threshold=0.6)

    # 5. 결과 출력 및 표시
    print("-" * 30)
    print(f" 탐지 결과: {count}명")
    print("-" * 30)
    print(" 창을 닫으려면 아무 키나 누르세요.")

    # 결과 이미지 크기가 너무 크면 조절해서 표시
    h, w = annotated_frame.shape[:2]
    display_scale = 1200 / w if w > 1200 else 1.0
    display_frame = cv2.resize(annotated_frame, (int(w * display_scale), int(h * display_scale)))

    cv2.imshow(f"Analysis Result - {count} People", display_frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # captures 폴더에 있는 파일 중 하나를 기본값으로 설정하거나 인자로 받음
    target_image = "captures/snapshot_P2_20260503_142944.jpg" # 예시 파일명
    
    if len(sys.argv) > 1:
        target_image = sys.argv[1]
    
    analyze_single_image(target_image)
