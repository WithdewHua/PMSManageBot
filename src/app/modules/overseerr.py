import requests
from app.config import settings


class Overseerr:
    def __init__(
        self,
        base_url: str = settings.OVERSEERR_BASE_URL,
        api_token: str = settings.OVERSEERR_API_TOKEN,
    ) -> None:
        self.base_url = base_url
        self.api_token = api_token
        self.base_headers = {
            "accept": "application/json",
            "X-Api-Key": self.api_token,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }

    def get_users(self, take=20, skip=0):
        try:
            response = requests.get(
                f"{self.base_url}/user?take={take}&skip={skip}",
                headers=self.base_headers,
            )
            if response:
                if response.status_code == 200:
                    return True, response.json()["results"]
                else:
                    return False, response.text
            else:
                return False, "Unknown error"
        except Exception as e:
            return False, str(e)

    def add_user(self, email: str, password: str, username=None):
        if len(password) < 8:
            return False, "Password must contain 8 characters at least"
        data = {"email": email, "password": password}
        if username:
            data.update({"username": username})
        try:
            response = requests.post(
                f"{self.base_url}/user", headers=self.base_headers, json=data
            )
            if response.status_code == 201:
                return True, response.json()["id"]
            else:
                return False, response.text
        except Exception as e:
            return False, str(e)
