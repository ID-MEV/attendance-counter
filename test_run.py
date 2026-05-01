import cv2
from detector import PersonDetector

detector = PersonDetector()
frame = cv2.imread('stream_snapshot.jpg')

if frame is not None:
     count, annotated_frame, _ = detector.detect_people(frame)
     print(f"\n>>> 탐지 결과: {count}명 발견!")
     cv2.imshow('Detection Result', annotated_frame)
     cv2.waitKey(0)
     cv2.destroyAllWindows()
else:
     print("이미지를 불러올 수 없습니다. 파일명을 확인해 주세요.")
