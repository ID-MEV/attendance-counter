import PyInstaller.__main__
import os
import shutil

def build():
    # 이전에 생성된 파일들 정리
    dirs_to_clean = ['build', 'dist']
    for d in dirs_to_clean:
        if os.path.exists(d):
            print(f"Cleaning up {d}...")
            shutil.rmtree(d)

    print("Building Executable...")
    
    # PyInstaller 설정
    PyInstaller.__main__.run([
        'gui_main.py',              # 메인 스크립트
        '--name=AttendanceCounter',  # 폴더/EXE 이름
        '--onedir',                  # 단일 파일 대신 폴더 구조 선택 (속도 향상 핵심)
        '--windowed',                # 콘솔 창 띄우지 않음
        '--noconfirm',               # 확인 절차 생략
        '--clean',                   # 캐시 삭제 후 빌드
        # YOLO 모델 파일 포함
        '--add-data=yolov8n.pt;.',   
        # 추가 패키지 힌트
        '--collect-all=ultralytics',
        '--collect-all=cv2',
        # 불필요하게 무거운 라이브러리 제외 (용량 및 속도 최적화)
        '--exclude-module=matplotlib',
        '--exclude-module=tensorboard',
        '--exclude-module=mkl',
    ])

    print("\nBuild Complete! Check the 'dist' folder.")

if __name__ == "__main__":
    build()
