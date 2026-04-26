import requests
from requests.auth import HTTPBasicAuth

class CameraController:
    def __init__(self, ip, user, password):
        self.ip = ip
        self.user = user
        self.password = password
        self.base_url = f"http://{self.ip}/cgi-bin/ptzctrl.cgi"

    def move_to_preset(self, preset_no):
        """
        지정된 프리셋 번호로 카메라를 이동시킵니다.
        :param preset_no: 이동할 프리셋 번호 (int)
        :return: 성공 여부 (bool), 메시지 (str)
        """
        params = {
            "ptzcmd": "",
            "poscall": "",
            f"{preset_no}": ""
        }
        
        # 실제 URL 형태: http://.../ptzctrl.cgi?ptzcmd&poscall&번호
        # requests의 params는 key=value 형태이므로, 
        # 위와 같이 value가 없는 key만 보내기 위해 직접 URL을 구성하거나 
        # 아래와 같이 문자열 처리를 수행합니다.
        
        url = f"{self.base_url}?ptzcmd&poscall&{preset_no}"
        
        try:
            response = requests.get(
                url, 
                auth=HTTPBasicAuth(self.user, self.password),
                timeout=5
            )
            
            if response.status_code == 200:
                print(f"[성공] 프리셋 {preset_no}번으로 이동 중...")
                return True, f"Preset {preset_no} moved"
            else:
                print(f"[오류] 상태 코드: {response.status_code}")
                return False, f"HTTP Error {response.status_code}"
                
        except Exception as e:
            print(f"[예외 발생] {str(e)}")
            return False, str(e)

if __name__ == "__main__":
    # 간단한 테스트 코드
    cam = CameraController("192.168.0.90", "admin", "admin")
    
    # 2번 프리셋으로 테스트 (사용자님이 확인하신 번호)
    success, msg = cam.move_to_preset(2)
    print(f"결과: {msg}")
