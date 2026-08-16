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

    def get_history(
        self,
        section_id=None,
        start_date=None,
        after=None,
        before=None,
        user_id=None,
        grouping=None,
        include_activity=None,
        media_type=None,
        order_column=None,
        order_dir=None,
        start=None,
        length=None,
    ):
        """Call Tautulli's get_history api endpoint

        Parameters
        ----------
        section_id : int, optional
            仅返回指定库的记录
        start_date : str, optional
            仅返回指定日期 (YYYY-MM-DD) 的记录
        after, before : str, optional
            日期区间 (YYYY-MM-DD)，闭区间
        user_id : int, optional
            仅返回指定用户的记录
        grouping : int, optional
            1 表示合并连续会话，0 表示逐条返回。
            做时长清洗时必须传 0：合并后 view_offset 取 MAX 而时长取 SUM，
            两者不再对应同一次播放，无法用播放进度校验时长。
        include_activity : int, optional
            1 表示把当前正在播放的会话一并返回，0 表示只返回已落库的历史。
            Tautulli 默认会带上活动会话，但这类记录尚未入库、没有 row_id、
            时长还在增长，既无法判定也无法删除，清洗时必须传 0。
        start, length : int, optional
            分页偏移与每页条数
        """
        payload = {}
        if section_id is not None:
            payload["section_id"] = int(section_id)
        if start_date:
            payload["start_date"] = start_date
        if after:
            payload["after"] = after
        if before:
            payload["before"] = before
        if user_id is not None:
            payload["user_id"] = int(user_id)
        if grouping is not None:
            payload["grouping"] = int(grouping)
        if include_activity is not None:
            payload["include_activity"] = int(include_activity)
        if media_type:
            payload["media_type"] = media_type
        if order_column:
            payload["order_column"] = order_column
        if order_dir:
            payload["order_dir"] = order_dir
        if start is not None:
            payload["start"] = int(start)
        if length is not None:
            payload["length"] = int(length)

        return self._call_api("get_history", payload)

    def iter_history(self, page_size: int = 1000, max_records: int = None, **kwargs):
        """分页遍历 get_history 的全部记录

        Tautulli 单次请求的返回条数有上限，这里按 page_size 翻页直到取完，
        逐条 yield history 记录。其余过滤参数透传给 :meth:`get_history`。
        """
        offset = 0
        fetched = 0
        while True:
            data = self.get_history(start=offset, length=page_size, **kwargs)
            if not data:
                break
            rows = data.get("data") or []
            if not rows:
                break
            for row in rows:
                yield row
                fetched += 1
                if max_records and fetched >= max_records:
                    return
            offset += len(rows)
            total = data.get("recordsFiltered")
            if total is not None and offset >= int(total):
                break

    def get_metadata(self, rating_key):
        """Call Tautulli's get_metadata api endpoint"""
        payload = {"rating_key": rating_key}

        return self._call_api("get_metadata", payload)

    def delete_history(self, row_ids) -> bool:
        """Call Tautulli's delete_history api endpoint

        删除指定的 history 记录，不可逆。row_ids 可以是单个 id、id 列表，
        或已经拼好的逗号分隔字符串。返回是否调用成功。

        这里用 raw=True 取整个 response 判断 result 字段，而不是看 data 是否为空：
        删除类接口成功时 data 可能就是 null，若据此判定失败，调用方会误以为
        没删掉而反复重试，并且永远不会把这批记录标记为已处理。
        """
        if isinstance(row_ids, (list, tuple, set)):
            row_ids = ",".join(str(row_id) for row_id in row_ids if row_id is not None)
        row_ids = str(row_ids or "").strip()
        if not row_ids:
            return False

        payload = {"row_ids": row_ids}
        response = self._call_api("delete_history", payload, raw=True)

        return bool(response) and response.get("result") == "success"

    def notify(self, notifier_id, subject, body):
        """Call Tautulli's notify api endpoint"""
        payload = {"notifier_id": notifier_id, "subject": subject, "body": body}

        return self._call_api("notify", payload)

    def _call_api(self, cmd, payload, method="GET", raw=False) -> dict:
        """调用 Tautulli API

        raw 为 True 时返回整个 response 对象（含 result / message / data），
        供需要区分「调用成功」与「data 为空」的接口使用；默认只返回 data，
        保持既有调用方的行为不变。
        """
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
            if raw:
                return response_json["response"]
            return response_json["response"]["data"]
        else:
            error_msg = response_json["response"]["message"]
            print("Tautulli API cmd '{}' failed: {}".format(cmd, error_msg))
            return

    def get_plex_current_playing_user_num(self) -> int:
        """Get user number of playing"""
        sessions: list[dict] = self.get_activity().get("sessions", [])
        num = 0
        for session in sessions:
            if session.get("state", "") == "playing":
                num += 1

        return num


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
