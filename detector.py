import cv2
from ultralytics import YOLO

class PersonDetector:
    def __init__(self, model_path='yolov8n.pt'):
        """
        YOLO 모델을 로드합니다. (기본값은 가벼운 yolov8n 모델)
        """
        print(f"모델 로드 중: {model_path}...")
        self.model = YOLO(model_path)
        # YOLO 클래스 인덱스 중 'person'은 대개 0번입니다.
        self.person_class_id = 0

    def detect_people(self, frame, conf_threshold=0.2, iou_threshold=0.5):
        """
        프레임에서 사람을 탐지하고 결과를 반환합니다.
        :param frame: OpenCV 프레임 (numpy array)
        :param conf_threshold: 신뢰도 임계값
        :param iou_threshold: 중복 제거 임계값
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
        
        # 사람만 탐지하도록 설정했으므로 res.plot()은 이제 사람만 그립니다.
        annotated_frame = res.plot() 
        
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
