import cv2
import time
from camera_controller import CameraController
from detector import PersonDetector

def run_test():
    # 1. 설정
    RTSP_URL = "rtsp://mev.o-r.kr:20003/stream1"
    CAMERA_IP = "192.168.0.90"
    USER = "admin"
    PW = "admin"
    
    # 2. 초기화
    print("시스템 초기화 중...")
    detector = PersonDetector(model_path='yolov8n.pt')
    cam = CameraController(CAMERA_IP, USER, PW)
    
    # 3. 카메라 프리셋 이동 테스트 (원하는 경우 주석 해제)
    # print("프리셋 2번으로 이동합니다.")
    # cam.move_to_preset(2)
    # time.sleep(2) # 이동 시간 대기
    
    # 4. RTSP 스트림 연결
    print(f"RTSP 스트림 연결 시도: {RTSP_URL}")
    cap = cv2.VideoCapture(RTSP_URL)
    
    if not cap.isOpened():
        print("오류: RTSP 스트림을 열 수 없습니다.")
        return

    print("스트림 연결 성공. 'q'를 누르면 종료합니다.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("프레임을 읽을 수 없습니다. 재연결 시도 중...")
            time.sleep(1)
            cap.open(RTSP_URL)
            continue
            
        # 5. 사람 탐지
        count, annotated_frame, _ = detector.detect_people(frame)
        
        # 6. 화면 표시
        display_frame = cv2.resize(annotated_frame, (1280, 720)) # 크기 조정
        cv2.putText(display_frame, f"People Count: {count}", (30, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        
        cv2.imshow("Seongrim Attendance Counter - Test", display_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_test()
