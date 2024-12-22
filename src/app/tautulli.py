#!/usr/bin/env python3
#

from app.config import settings
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException


class Tautulli(object):
    def __init__(
        self,
        url=settings.TAUTULLI_URL,
        apikey=settings.TAUTULLI_APIKEY,
        verify_ssl=settings.TAUTULLI_VERIFY_SSL,
        debug=None,
    ):
        self.url = url
        self.apikey = apikey
        self.debug = debug

        self.session = Session()
        self.adapters = HTTPAdapter(
            max_retries=3, pool_connections=1, pool_maxsize=1, pool_block=True
        )
        self.session.mount("http://", self.adapters)
        self.session.mount("https://", self.adapters)

        # Ignore verifying the SSL certificate
        if verify_ssl is False:
            self.session.verify = False
            # Disable the warning that the request is insecure, we know that...
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get_activity(self):
        "Call Tautulli's get_activity api endpoint"
        payload = {}

        return self._call_api("get_activity", payload)

    def get_library_media_info(self, section_id=None, refresh=None):
        """Call Tautulli's get_library_media_info api endpoint"""
        payload = {}
        if refresh:
            for library in self.get_libraries():
                payload["section_id"] = library["section_id"]
                payload["refresh"] = "true"
                print("Refreshing library: {}".format(library["section_name"]))
                self._call_api("get_library_media_info", payload)
            print(
                "Libraries have been refreshed, please wait while library stats are updated."
            )
            exit()
        else:
            payload["section_id"] = section_id

        return self._call_api("get_library_media_info", payload)

    def get_libraries(self):
        """Call Tautulli's get_libraries api endpoint"""
        payload = {}

        return self._call_api("get_libraries", payload)

    def get_home_stats(self, time_range, stats_type, stats_count, stat_id=None):
        """Call Tautulli's get_home_stats api endpoint"""
        payload = {}
        payload["time_range"] = time_range
        payload["stats_type"] = stats_type
        payload["stats_count"] = stats_count
        if stat_id:
            payload["stat_id"] = stat_id

        return self._call_api("get_home_stats", payload)

    def get_history(self, section_id, check_date):
        """Call Tautulli's get_history api endpoint"""
        payload = {}
        payload["section_id"] = int(section_id)
        payload["start_date"] = check_date

        return self._call_api("get_history", payload)

    def notify(self, notifier_id, subject, body):
        """Call Tautulli's notify api endpoint"""
        payload = {"notifier_id": notifier_id, "subject": subject, "body": body}

        return self._call_api("notify", payload)

    def _call_api(self, cmd, payload, method="GET") -> dict:
        payload["cmd"] = cmd
        payload["apikey"] = self.apikey

        try:
            response = self.session.request(
                method, self.url + "/api/v2", params=payload
            )
        except RequestException as e:
            print(
                "Tautulli request failed for cmd '{}'. Invalid Tautulli URL? Error: {}".format(
                    cmd, e
                )
            )
            return

        try:
            response_json = response.json()
        except ValueError:
            print(
                "Failed to parse json response for Tautulli API cmd '{}': {}".format(
                    cmd, response.content
                )
            )
            return

        # print(response_json["response"])
        if response_json["response"]["result"] == "success":
            if self.debug:
                print("Successfully called Tautulli API cmd '{}'".format(cmd))
            return response_json["response"]["data"]
        else:
            error_msg = response_json["response"]["message"]
            print("Tautulli API cmd '{}' failed: {}".format(cmd, error_msg))
            return


class Notification(object):
    def __init__(self, notifier_id, subject, body, tautulli, stats=None):
        self.notifier_id = notifier_id
        self.subject = subject
        self.body = body

        self.tautulli = tautulli
        if stats:
            self.stats = stats

    def send(self, subject="", body=""):
        """Send to Tautulli notifier.

        Parameters
        ----------
        subject : str
            Subject of the message.
        body : str
            Body of the message.
        """
        subject = subject or self.subject
        body = body or self.body
        self.tautulli.notify(notifier_id=self.notifier_id, subject=subject, body=body)
