import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException, ConnectionError, Timeout
from logger_setup import logger # 로거 임포트

class CameraController:
    def __init__(self, ip, user, password, port=None):
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        if self.port:
            self.base_url = f"http://{self.ip}:{self.port}/cgi-bin/ptzctrl.cgi"
        else:
            self.base_url = f"http://{self.ip}/cgi-bin/ptzctrl.cgi"
        logger.info(f"CameraController 초기화: IP={ip}, Port={port}, 사용자={user}")

    def _send_command(self, url, command_name):
        try:
            response = requests.get(
                url, 
                auth=HTTPBasicAuth(self.user, self.password),
                timeout=5 # 연결 타임아웃 5초 설정
            )
            
            if response.status_code == 200:
                logger.info(f"[성공] {command_name} - 상태 코드: {response.status_code}")
                return True, f"{command_name} 성공"
            else:
                logger.error(f"[오류] {command_name} - HTTP 상태 코드: {response.status_code}, 응답: {response.text}")
                return False, f"HTTP 오류 {response.status_code}"
                
        except ConnectionError as e:
            logger.error(f"[네트워크 오류] {command_name} - 연결 실패: {e}", exc_info=True)
            return False, f"네트워크 연결 오류: {e}"
        except Timeout as e:
            logger.error(f"[네트워크 오류] {command_name} - 요청 시간 초과: {e}", exc_info=True)
            return False, f"요청 시간 초과 오류: {e}"
        except RequestException as e:
            logger.error(f"[요청 오류] {command_name} - 요청 중 예외 발생: {e}", exc_info=True)
            return False, f"요청 예외 발생: {e}"
        except Exception as e:
            logger.error(f"[알 수 없는 오류] {command_name} - 예측하지 못한 예외 발생: {e}", exc_info=True)
            return False, f"알 수 없는 오류: {e}"

    def move_to_preset(self, preset_no):
        """
        지정된 프리셋 번호로 카메라를 이동시킵니다.
        :param preset_no: 이동할 프리셋 번호 (int)
        :return: 성공 여부 (bool), 메시지 (str)
        """
        url = f"{self.base_url}?ptzcmd&poscall&{preset_no}"
        return self._send_command(url, f"프리셋 {preset_no}번 이동")

    def move_continuous(self, direction, speed_param1=10, speed_param2=10):
        """
        지정된 방향으로 카메라를 연속적으로 움직입니다.
        :param direction: 움직일 방향 (예: "right", "left", "up", "down", "zoomin", "zoomout")
        :param speed_param1: 속도 또는 관련 파라미터 1
        :param speed_param2: 속도 또는 관련 파라メータ 2 (줌에는 사용되지 않음)
        :return: 성공 여부 (bool), 메시지 (str)
        """
        if direction in ["zoomin", "zoomout"]:
            url = f"{self.base_url}?ptzcmd&{direction}&{speed_param1}" # 줌 명령은 speed_param2 없음
        else:
            url = f"{self.base_url}?ptzcmd&{direction}&{speed_param1}&{speed_param2}"
        return self._send_command(url, f"카메라 {direction} 방향으로 움직임 시작")

    def stop_movement(self, command_type="move"): # command_type 파라미터 추가
        """
        카메라의 연속적인 움직임을 중지합니다.
        :param command_type: 중지할 움직임의 종류 ("move" 또는 "zoom")
        :return: 성공 여부 (bool), 메시지 (str)
        """
        if command_type == "zoom":
            url = f"{self.base_url}?ptzcmd&zoomstop&5" # 줌 중지 명령은 파라미터 5
        else:
            url = f"{self.base_url}?ptzcmd&ptzstop&0&0" # 일반 이동 중지 명령
        return self._send_command(url, "카메라 움직임 중지")
