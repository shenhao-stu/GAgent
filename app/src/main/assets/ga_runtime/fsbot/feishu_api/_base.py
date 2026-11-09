# -*- coding: utf-8 -*-
"""飞书 API 基类 — 统一调用/分页/权限检测。

核心事实（实测 lark_native.api 源码）:
  · api() 成功(code==0) 返回 j["data"]（已剥离 code/msg/外层）
  · api() 失败(code!=0) raise RuntimeError("path code=X msg=Y")
  · api() 仅支持 JSON body，二进制上传/下载需域内直连 requests
"""

import re
import lark_native

_OPEN = lark_native._OPEN   # open.feishu.cn/open-apis 基址

_ERR_CODE_RE = re.compile(r"code=(\d+)")


def _parse_err_code(msg):
    """从 lark_native.api() 抛出的 RuntimeError 消息中解析错误码。

    消息格式: "/calendar/v4/calendars code=99992402 msg=field validation failed"
    """
    m = _ERR_CODE_RE.search(msg or "")
    return int(m.group(1)) if m else None


def _build_setup_url(scopes):
    """生成飞书开发者后台权限开通链接。"""
    try:
        app_id = lark_native._creds()[0]   # 实测: _creds() 返回 (app_id, ...)
    except Exception:
        app_id = ""
    return (f"https://open.feishu.cn/app/{app_id}/permission"
            f"?scope={','.join(scopes)}")


class FeishuApiError(Exception):
    """飞书 API 错误（携带 code，供权限检测判断）。"""

    def __init__(self, msg, code=None, raw=None):
        super().__init__(msg)
        self.code = code
        self.raw = raw


class FeishuApiBase:
    _domain_name = ""
    _scopes = []

    def __init__(self, as_user=False):
        self.as_user = as_user

    # ------------------------------------------------------------------
    # 核心调用
    # ------------------------------------------------------------------

    def _call(self, method, path, params=None, payload=None, dry_run=False):
        """统一调用入口。返回 api() 的 data 部分。

        Raises:
            FeishuApiError: 携带 code（从 RuntimeError 解析）
        """
        if dry_run:
            return {"_dry_run": True, "method": method, "path": path,
                    "params": params, "payload": payload}
        try:
            return lark_native.api(method, path, params=params,
                                   payload=payload, as_user=self.as_user)
        except RuntimeError as e:
            # api() 失败时抛 RuntimeError，从中解析 code
            raise FeishuApiError(str(e), code=_parse_err_code(str(e)),
                                raw=str(e)) from e
        except FeishuApiError:
            raise
        except Exception as e:
            raise FeishuApiError(f"API 调用失败: {e}", raw=str(e)) from e

    def _paginate(self, method, path, params=None, payload=None,
                  page_size=50, max_pages=20, items_key="items"):
        """自动分页。

        items_key 由各域按真实结构指定:
            im chats / calendar events / docx blocks → "items"
            drive files → "files"
            calendar list 不用此方法（calendar_list 是一次性 list）
        """
        if params is None:
            params = {}
        params.setdefault("page_size", page_size)

        all_items = []
        page_token = None
        for _ in range(max_pages):
            if page_token:
                params["page_token"] = page_token
            elif "page_token" in params:
                del params["page_token"]

            result = self._call(method, path, params=params, payload=payload)
            if not isinstance(result, dict):
                break
            items = result.get(items_key, [])
            if not isinstance(items, list):
                items = []
            all_items.extend(items)

            if not result.get("has_more", False):
                break
            page_token = result.get("page_token", "")
            if not page_token:
                break
        return all_items

    # ------------------------------------------------------------------
    # 权限检测
    # ------------------------------------------------------------------

    def check_scopes(self):
        """检查本域权限。返回 {granted, missing_scopes, setup_url}。

        探测调用若因权限不足(code=99991663)失败 → granted=False；
        其他错误（如参数校验）说明权限通了 → granted=True。
        """
        try:
            probe = self._probe_permission()
            if probe:
                return probe
            return {"granted": True, "missing_scopes": [], "setup_url": None}
        except FeishuApiError as e:
            if e.code == 99991663:
                return {"granted": False,
                        "missing_scopes": list(self._scopes),
                        "setup_url": _build_setup_url(self._scopes)}
            return {"granted": True, "missing_scopes": [],
                    "setup_url": None}

    def _probe_permission(self):
        """子类覆盖：用一次轻量调用探测权限。返回 None 走默认逻辑。"""
        return None

    @staticmethod
    def _pick(data, *keys):
        return tuple(data.get(k, "--") for k in keys)
