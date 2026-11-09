# -*- coding: utf-8 -*-
"""APK 工厂 scaffold（设备端）: 复制 apk_factory_template → 改包名/应用名 → 产出立即可编译的钉版工程。
Chaquopy 进程内用: `import scaffold; proj = scaffold.scaffold("app.ga.xxx", "应用名", "temp/proj")`。
产出的工程已是可离线编译的钉版(compileSdk 35 / AGP 8.6.0 / Gradle 8.9)——GA 在里面写真实代码，别动版本行。"""
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_PKG = "app.ga.starter"
SEED_LABEL = "GA Starter"
PKG_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")


def _template_dir():
    for name in ("apk_factory_template", "template"):
        p = os.path.join(HERE, name)
        if os.path.isdir(p):
            return p
    raise FileNotFoundError("找不到模板目录 apk_factory_template")


def scaffold(pkg, label, out):
    if not PKG_RE.fullmatch(pkg or ""):
        raise ValueError("包名须小写反向域名(a.b.c): %r" % pkg)
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(_template_dir(), out)

    for root, _, files in os.walk(out):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                txt = open(fp, encoding="utf-8").read()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            new = txt.replace(SEED_PKG, pkg)
            if fn == "strings.xml":
                new = new.replace(">%s<" % SEED_LABEL, ">%s<" % label)
            if new != txt:
                open(fp, "w", encoding="utf-8").write(new)

    kroot = os.path.join(out, "app", "src", "main", "kotlin")
    old_dir = os.path.join(kroot, *SEED_PKG.split("."))
    new_dir = os.path.join(kroot, *pkg.split("."))
    if os.path.abspath(old_dir) != os.path.abspath(new_dir) and os.path.isdir(old_dir):
        os.makedirs(new_dir, exist_ok=True)
        for f in os.listdir(old_dir):
            shutil.move(os.path.join(old_dir, f), os.path.join(new_dir, f))
        d = old_dir
        while os.path.abspath(d) != os.path.abspath(kroot) and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)
    return out
