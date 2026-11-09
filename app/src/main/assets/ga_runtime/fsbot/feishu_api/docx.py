# -*- coding: utf-8 -*-
"""文档域 — 文档列表/读取内容/编辑文本块。"""

from ._base import FeishuApiBase, FeishuApiError


class DocxAPI(FeishuApiBase):
    _domain_name = "docx"
    _scopes = ["docx:document", "docx:document:readonly",
               "drive:drive:readonly"]

    # ------------------------------------------------------------------
    # 文档列表 (借云空间 API 列 docx 类型)
    # ------------------------------------------------------------------

    def list_documents(self, page_size=20):
        """列出 docx 文档。

        docx/v1/documents 不支持列表，故借 /drive/v1/files 列出后
        客户端过滤 type==docx。
        """
        from .drive import DriveAPI
        drive = DriveAPI(as_user=self.as_user)
        files = drive.list_files(page_size=page_size)
        return [f for f in files if f.get("type") == "docx"]

    def _probe_permission(self):
        """探测: 列文档。"""
        self.list_documents()
        return None

    # ------------------------------------------------------------------
    # 读取文档块
    # ------------------------------------------------------------------

    def get_blocks(self, document_id, page_size=500):
        """获取文档所有块。

        实测结构: /docx/v1/documents/{id}/blocks → {items:[...], page_token, has_more}
        """
        params = {"page_size": page_size}
        return self._paginate(
            "GET", f"/docx/v1/documents/{document_id}/blocks",
            params=params, items_key="items", max_pages=10)

    def get_text(self, document_id):
        """提取文档纯文本（聚合所有文本块）。"""
        blocks = self.get_blocks(document_id)
        lines = []
        for b in blocks:
            text = ""
            txt = b.get("text", {})
            if isinstance(txt, dict):
                for el in txt.get("elements", []):
                    if isinstance(el, dict) and "text_run" in el:
                        text += el["text_run"].get("content", "")
            if text:
                lines.append(text)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 编辑文本块
    # ------------------------------------------------------------------

    def update_block_text(self, document_id, block_id, new_text):
        """更新指定文本块的内容。"""
        payload = {
            "update_text_elements": {
                "elements": [{"text_run": {"content": new_text}}]
            }
        }
        return self._call(
            "PATCH",
            f"/docx/v1/documents/{document_id}/blocks/{block_id}",
            payload=payload)

    def create_document(self, folder_token=None):
        """创建空文档。返回 {document_id, revision_id}。
        folder_token 指定父文件夹(默认根目录)。
        scope: docx:document(读写)。
        """
        params = {"folder_token": folder_token} if folder_token else None
        result = self._call("POST", "/docx/v1/documents", params=params)
        return result   # {"document": {"document_id":..., "revision_id":-1}}

    def add_text_blocks(self, document_id, lines):
        """向文档根块追加文本块(每行一个段落)。
        根块 block_id = document_id。空行用单空格占位(飞书不接受空 content)。
        """
        if isinstance(lines, str):
            lines = lines.splitlines()
        children = []
        for ln in lines:
            children.append({
                "block_type": 2,
                "text": {
                    "elements": [{"text_run": {"content": ln or " "}}],
                    "style": {}
                }
            })
        if not children:
            return []
        payload = {"index": 0, "children": children}
        return self._call(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            payload=payload)
