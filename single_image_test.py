import cv2
import sys
import os
import numpy as np
from detector import PersonDetector

def analyze_single_image(image_path, use_tiling=True):
    # 1. 파일 존재 확인
    if not os.path.exists(image_path):
        print(f"[오류] 파일을 찾을 수 없습니다: {image_path}")
        return

    # 2. 탐지기 초기화
    print("탐지기 로드 중 (yolov8l)...")
    detector = PersonDetector()
    
    # 3. 이미지 읽기
    original_frame = cv2.imread(image_path)
    if original_frame is None:
        print(f"[오류] 이미지를 불러올 수 없습니다: {image_path}")
        return

    h, w = original_frame.shape[:2]
    all_boxes = []

    # 4. 분석 실행 (전체 화면 + 세밀한 타일링)
    print(f"분석 시작 (Tiling: {use_tiling}): {image_path}")
    
    # 기본 전체 화면 탐지 (임계값 0.1로 복구)
    _, _, boxes = detector.detect_people(original_frame, conf_threshold=0.1, iou_threshold=0.6)
    for box in boxes:
        all_boxes.append({
            'xyxy': box.xyxy[0].cpu().numpy(),
            'conf': float(box.conf[0])
        })

    if use_tiling:
        print("세밀한 타일링 분석 중 (3x3 Grid)...")
        # 3x3 타일로 더 잘게 나누어 분석 (오버랩 25%로 상향)
        rows, cols = 3, 3
        overlap = 0.25
        tile_h, tile_w = int(h / rows), int(w / cols)
        
        for i in range(rows):
            for j in range(cols):
                # 각 타일의 시작/끝 좌표 계산 (오버랩 포함)
                y_start = max(0, int(i * tile_h - (tile_h * overlap if i > 0 else 0)))
                y_end = min(h, int((i + 1) * tile_h + (tile_h * overlap if i < rows - 1 else 0)))
                x_start = max(0, int(j * tile_w - (tile_w * overlap if j > 0 else 0)))
                x_end = min(w, int((j + 1) * tile_w + (tile_w * overlap if j < cols - 1 else 0)))
                
                tile = original_frame[y_start:y_end, x_start:x_end]
                # 타일 분석도 임계값 0.1 적용
                _, _, t_boxes = detector.detect_people(tile, conf_threshold=0.1, iou_threshold=0.6)
                
                for tb in t_boxes:
                    coords = tb.xyxy[0].cpu().numpy()
                    # 전체 좌표계로 변환
                    global_coords = [
                        coords[0] + x_start,
                        coords[1] + y_start,
                        coords[2] + x_start,
                        coords[3] + y_start
                    ]
                    all_boxes.append({
                        'xyxy': global_coords,
                        'conf': float(tb.conf[0])
                    })

    # 5. 박스 통합 및 중복 제거 (Advanced NMS)
    final_boxes = []
    if all_boxes:
        # 신뢰도 순으로 정렬 (높은 신뢰도 박스 우선)
        sorted_boxes = sorted(all_boxes, key=lambda x: x['conf'], reverse=True)
        
        while sorted_boxes:
            best = sorted_boxes.pop(0)
            final_boxes.append(best)
            
            remaining = []
            for item in sorted_boxes:
                iou = calculate_iou(best['xyxy'], item['xyxy'])
                iom = calculate_iom(best['xyxy'], item['xyxy'])
                
                # 1. IOU가 0.4 이상이거나 (겹침이 많음)
                # 2. IoM이 0.7 이상인 경우 (한 박스가 다른 박스에 70% 이상 포함됨)
                # 중복으로 간주하여 제외
                if iou < 0.4 and iom < 0.7:
                    remaining.append(item)
            sorted_boxes = remaining

    # 6. 결과 그리기
    annotated_frame = original_frame.copy()
    for box in final_boxes:
        x1, y1, x2, y2 = map(int, box['xyxy'])
        # 박스 색상을 녹색으로 변경하고 두께 조정
        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(annotated_frame, f"{box['conf']:.2f}", (x1, y1 - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 0), 1)

    count = len(final_boxes)
    print("-" * 30)
    print(f" 정제된 탐지 결과: {count}명")
    print("-" * 30)

    # 화면 표시
    display_scale = 1200 / w if w > 1200 else 1.0
    display_frame = cv2.resize(annotated_frame, (int(w * display_scale), int(h * display_scale)))
    cv2.imshow(f"Cleaned Analysis - {count} People", display_frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

def calculate_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0

def calculate_iom(box1, box2):
    """
    Intersection over Minimum: 한 박스가 다른 박스에 포함되는 정도를 계산
    """
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    min_area = min(area1, area2)
    
    return intersection / min_area if min_area > 0 else 0

if __name__ == "__main__":
    target_image = "captures/snapshot_P3_20260503_142950.jpg"
    if len(sys.argv) > 1:
        target_image = sys.argv[1]
    
    analyze_single_image(target_image)
