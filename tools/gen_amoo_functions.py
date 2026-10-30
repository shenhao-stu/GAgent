#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 amoo(AppFunctions) 的元数据 XML。

GA 通过标准 android.app.appfunctions 把能力暴露给 StepOS 的语音助手 amoo
(com.stepos.ailauncher): amoo 用 BM25 检索本机所有 AppFunctions 的
name+description 来选工具, 所以描述里的"微信/小程序/去微信"等词就是触发词。

产物(assets, 由 AndroidManifest 的 service property 引用):
  app/src/main/assets/amoo/app_functions.xml      # 旧版 schema: function_id + enabled_by_default
  app/src/main/assets/amoo/app_functions_v2.xml   # 新版 schema: id/description/parameters/response
  app/src/main/assets/amoo/app_functions_schema.xsd  # 手写置入, 不由此脚本生成

跑法: python tools/gen_amoo_functions.py   (改完描述重跑, 提交 assets)
"""
import pathlib
import xml.etree.ElementTree as ET

BASE = pathlib.Path(__file__).resolve().parents[1]
OUT = BASE / "app" / "src" / "main" / "assets" / "amoo"
SVC = "com.ljq.ga.amoo.GaAppFunctionService"

FUNCTIONS = [
    ("capabilities",
     "GAgent 能做什么: 自动化操作手机界面，包括在微信里打开小程序、在小程序里逐页翻找、"
     "点击按钮、滑动列表、输入文字、截图看画面判断，完成多步骤任务。"
     "用户问「本机有没有能自动操作其他 App 界面、模拟点击、无障碍脚本」这类问题时用本工具查询。",
     []),
    ("startTask",
     "自动化操作手机界面: 代替用户在微信等 App 里点击、滑动、输入、截图判断，完成多步骤任务。"
     "能做到: 打开微信、搜索聊天/公众号/小程序、进入小程序、在小程序里逐页翻找、点按钮、填表, "
     "并把结果原样报回来。用户说「去微信…」「打开微信…」「在微信里…」「进小程序…」"
     "「帮我一步步操作…」时用本工具; 不要只用 open_app_by_name 打开 App 就结束。"
     "立即返回 taskId, 之后用 taskStatus 查进度。",
     [("task", "要完成的中文任务原话, 例如: 去微信搜索三角洲行动并进入小程序查看今日密码", True)]),
    ("taskStatus",
     "查询 GAgent 手机自动化任务的进度与结果: 返回 state(running/done)、当前步骤摘要、最终回复。"
     "startTask 返回后轮询用。",
     [("taskId", "startTask 返回的 taskId; 留空表示查询最近一次任务", False)]),
    ("cancelTask",
     "取消 GAgent 正在执行的手机自动化任务。",
     [("taskId", "要取消的 taskId; 留空表示取消最近一次任务", False)]),
]


def add(parent, name, text=None):
    e = ET.SubElement(parent, name)
    if text is not None:
        e.text = str(text)
    return e


def main():
    out = pathlib.Path(OUT)
    out.mkdir(parents=True, exist_ok=True)
    legacy = ET.Element("appfunctions")
    modern = ET.Element("appfunctions")
    for method, description, parameters in FUNCTIONS:
        fid = SVC + "#" + method
        row_old = add(legacy, "appfunction")
        add(row_old, "function_id", fid)
        add(row_old, "enabled_by_default", "true")
        row = add(modern, "appfunction")
        add(row, "id", fid)
        add(row, "enabledByDefault", "true")
        add(row, "description", description)
        for name, desc, required in parameters:
            p = add(row, "parameters")
            meta = add(p, "dataTypeMetadata")
            add(meta, "id", "unused")
            add(meta, "isNullable", "false" if required else "true")
            add(meta, "type", 8)
            add(p, "id", "unused")
            add(p, "isRequired", "true" if required else "false")
            add(p, "name", name)
            add(p, "description", desc)
        resp = add(row, "response")
        add(resp, "id", "unused")
        value = add(resp, "valueType")
        add(value, "id", "unused")
        add(value, "isNullable", "false")
        add(value, "type", 8)
        add(row, "functionId", fid)
    for name, root in (("app_functions.xml", legacy), ("app_functions_v2.xml", modern)):
        ET.indent(root, space="  ")
        path = out / name
        path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        print("wrote", path, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
