import cv2
import time

def capture_snapshot():
    RTSP_URL = "rtsp://mev.o-r.kr:20003/stream1"
    print(f"RTSP 스트림 연결 시도: {RTSP_URL}")
    
    cap = cv2.VideoCapture(RTSP_URL)
    
    if not cap.isOpened():
        print("오류: 스트림에 연결할 수 없습니다.")
        return

    # 연결 직후 첫 프레임은 깨질 수 있으므로 잠시 대기 후 몇 프레임 건너뜁니다.
    time.sleep(2)
    for _ in range(5):
        cap.grab()
        
    ret, frame = cap.read()
    
    if ret:
        filename = "stream_snapshot.jpg"
        cv2.imwrite(filename, frame)
        print(f"성공: 현재 화면이 '{filename}'으로 저장되었습니다.")
    else:
        print("오류: 프레임을 읽을 수 없습니다.")
        
    cap.release()

if __name__ == "__main__":
    capture_snapshot()
