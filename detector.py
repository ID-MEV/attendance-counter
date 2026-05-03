import cv2
from ultralytics import YOLO

class PersonDetector:
    def __init__(self, model_path='yolov8l.pt'):
        """
        YOLO 모델을 로드합니다. (최고의 정밀도를 위해 Large 모델을 사용)
        """
        print(f"모델 로드 중: {model_path}...")
        self.model = YOLO(model_path)
        # YOLO 클래스 인덱스 중 'person'은 대개 0번입니다.
        self.person_class_id = 0

    def detect_people(self, frame, conf_threshold=0.1, iou_threshold=0.6):
        """
        프레임에서 사람을 탐지하고 결과를 반환합니다.
        감도를 높이기 위해 기본 신뢰도(conf)를 낮추고, 
        사람이 겹쳐있을 때 각각의 박스를 유지하도록 IOU를 높였습니다.
        :param frame: OpenCV 프레임 (numpy array)
        :param conf_threshold: 신뢰도 임계값 (0.1로 낮추어 형체만 있어도 인식)
        :param iou_threshold: 중복 제거 임계값 (0.6으로 높여 겹친 사람 분리)
        :return: 탐지된 인원수, 결과 프레임, 바운딩 박스 리스트
        """
        # classes=[0]을 추가하여 오직 '사람'만 탐지하도록 제한 (속도 및 정확도 향상)
        results = self.model(frame, 
                             conf=conf_threshold, 
                             iou=iou_threshold, 
                             classes=[0], 
                             verbose=False)
        
        res = results[0]
        count = len(res.boxes)
        
        # 가독성을 높이기 위한 커스텀 그리기 로직 (선 두께와 폰트 크기 조정)
        annotated_frame = frame.copy()
        for box in res.boxes:
            # 좌표 추출
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            
            # 박스 그리기 (선 두께 1로 축소하여 겹침 확인 용이하게 함)
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 1)
            
            # 레이블 표시 (신뢰도 포함, 폰트 크기 축소)
            label = f"{conf:.2f}"
            cv2.putText(annotated_frame, label, (x1, y1 - 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
        return count, annotated_frame, res.boxes

if __name__ == "__main__":
    # 웹캠 등으로 간단 테스트 (카메라가 연결되어 있어야 함)
    detector = PersonDetector()
    cap = cv2.VideoCapture(0) # 0번 카메라
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        count, out_frame, _ = detector.detect_people(frame)
        
        cv2.putText(out_frame, f"Count: {count}", (50, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("Detection Test", out_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()
