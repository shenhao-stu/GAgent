# -*- coding: utf-8 -*-
"""云空间域 — 文件列表/上传/下载。

上传/下载用 lark_native.requests + tenant_token() 直连，
绕过 api() 的 JSON-only 限制（api() 无法处理 multipart / 二进制流）。
"""

import os
import lark_native
from ._base import FeishuApiBase, FeishuApiError, _OPEN


class DriveAPI(FeishuApiBase):
    _domain_name = "drive"
    _scopes = ["drive:drive", "drive:drive:readonly",
               "docs:document:create", "drive:file:upload"]

    # ------------------------------------------------------------------
    # 文件列表
    # ------------------------------------------------------------------

    def list_files(self, folder_token=None, page_size=50):
        """列出云空间文件。

        实测结构: /drive/v1/files → {"files":[...], "has_more"}
        """
        params = {"page_size": page_size}
        if folder_token:
            params["folder_token"] = folder_token
        return self._paginate("GET", "/drive/v1/files",
                             params=params, items_key="files")

    def _probe_permission(self):
        """探测: 列文件。"""
        self.list_files(page_size=1)
        return None

    # ------------------------------------------------------------------
    # 上传 (直连 multipart)
    # ------------------------------------------------------------------

    def upload_file(self, file_path, file_name=None, parent_token=None,
                    parent_type="explorer", dry_run=False):
        """上传本地文件到云空间。返回 {file_token}。

        直连实现: api() 只支持 JSON body，无法 multipart，故直接用
        lark_native.requests + tenant_token()。
        """
        if dry_run:
            return {"_dry_run": True, "file_path": file_path,
                    "file_name": file_name, "parent_token": parent_token}
        file_name = file_name or os.path.basename(file_path)
        if not os.path.isfile(file_path):
            raise FeishuApiError(f"本地文件不存在: {file_path}")
        size = os.path.getsize(file_path)

        token = lark_native.tenant_token()
        url = _OPEN + "/drive/v1/files/upload_all"
        params = {"file_name": file_name, "parent_type": parent_type,
                  "size": str(size)}
        if parent_token:
            params["parent_token"] = parent_token
        headers = {"Authorization": "Bearer " + token}

        with open(file_path, "rb") as f:
            r = lark_native.requests.post(url, params=params, headers=headers,
                                          files={"file_name": (file_name, f)},
                                          timeout=180)
        j = r.json()
        if j.get("code") != 0:
            raise FeishuApiError(f"上传失败: {j.get('msg')}",
                                 code=j.get("code"), raw=j)
        return j.get("data", j)

    # ------------------------------------------------------------------
    # 下载 (直连读二进制)
    # ------------------------------------------------------------------

    def download_file(self, file_token, save_path=None, dry_run=False):
        """下载云空间文件到本地。返回保存路径或 bytes。

        直连实现: api() 用 _json() 解析响应，二进制下载必失败，故直连。
        """
        if dry_run:
            return {"_dry_run": True, "file_token": file_token,
                    "save_path": save_path}
        token = lark_native.tenant_token()
        url = _OPEN + f"/drive/v1/files/{file_token}/download"
        headers = {"Authorization": "Bearer " + token}
        r = lark_native.requests.get(url, headers=headers, timeout=180)

        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            # 错误响应（如权限不足/token无效）返回 JSON
            try:
                j = r.json()
                raise FeishuApiError(f"下载失败: {j.get('msg')}",
                                     code=j.get("code"), raw=j)
            except (ValueError, KeyError):
                raise FeishuApiError(f"下载失败: HTTP {r.status_code}")

        data = r.content
        if save_path:
            save_dir = os.path.dirname(save_path)
            if save_dir and not os.path.isdir(save_dir):
                os.makedirs(save_dir, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(data)
            return save_path
        return data
