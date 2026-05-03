import requests
import json
import os

class KakaoNotifier:
    def __init__(self, token_file='kakao_token.json'):
        self.token_file = token_file
        self.access_token = self._load_token()

    def _load_token(self):
        """파일에서 토큰을 로드합니다."""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    return data.get('access_token')
            except:
                return None
        return None

    def send_message(self, text):
        """
        카카오톡 '나에게 보내기' API를 사용하여 메시지를 전송합니다.
        :param text: 전송할 메시지 내용
        :return: 성공 여부 (bool)
        """
        if not self.access_token:
            print("[경고] 카카오 액세스 토큰이 없습니다. 메시지를 보낼 수 없습니다.")
            return False

        url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        template_object = {
            "object_type": "text",
            "text": text,
            "link": {
                "web_url": "http://mev.o-r.kr:20003",
                "mobile_web_url": "http://mev.o-r.kr:20003"
            },
            "button_title": "확인"
        }
        
        data = {
            "template_object": json.dumps(template_object)
        }
        
        try:
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                print("[성공] 카카오톡 메시지가 전송되었습니다.")
                return True
            else:
                print(f"[오류] 카카오 API 응답 실패: {response.status_code}, {response.text}")
                return False
        except Exception as e:
            print(f"[예외 발생] 카카오 메시지 전송 중 오류: {str(e)}")
            return False

    def update_token(self, new_token):
        """새로운 토큰을 저장합니다."""
        self.access_token = new_token
        with open(self.token_file, 'w') as f:
            json.dump({'access_token': new_token}, f)
        print("[정보] 카카오 토큰이 업데이트되었습니다.")

if __name__ == "__main__":
    # 간단한 테스트 (토큰이 있을 경우)
    notifier = KakaoNotifier()
    if notifier.access_token:
        notifier.send_message("테스트 메시지입니다. 인원 분석 결과: 10명")
    else:
        print("kakao_token.json 파일에 'access_token'을 입력해주세요.")
