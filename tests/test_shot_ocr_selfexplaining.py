"""截屏与 OCR 入口的"自解释"改造——两处都有真机实证的整轮浪费。

证据(不是推测):
1. 模型的回合小结原句: "droid.shot() 返回 numpy 数组。改用 numpy …" ——
   它花了**一整个轮次**去 print(shot()) 才把返回类型搞清楚。phone_use.md §1
   也早就写明"print(shot()) 只会输出数字, 模型看不到图片", 但模型照犯:
   默认 repr 吐出一堆数字, 看起来"像是有内容"。
2. 模型写 `img = droid.shot(); crop = img.crop((0,150,1200,800)); droid.ocr(crop)`
   —— crop 是 PIL Image(shot() 返回 ndarray, 没有 .crop), 整轮抛异常,
   下一轮才改成 numpy 切片。

共同点: 都不是模型笨, 是入口不解释自己。报错/回显只说"是什么", 不说"该改成什么",
模型就得再花一轮去试。这里把两边都改成一次说清。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import droid


class ShotReprTest(unittest.TestCase):
    """print(shot()) 必须给出可执行的下一步, 而不是一串数字。"""

    def _img(self, h=2670, w=1200, c=3):
        return np.zeros((h, w, c), dtype=np.uint8).view(droid._shot_img_cls())

    def test_repr_is_a_hint_not_a_wall_of_numbers(self):
        s = repr(self._img())
        self.assertIn('screenshot 1200x2670x3', s)
        self.assertIn('print() cannot show an image', s)
        # 必须指出正确的三个用法, 否则模型只知道"不能 print", 不知道该怎么办
        for fn in ('ask_vision', 'droid.ocr', 'droid.look'):
            self.assertIn(fn, s)
        self.assertLess(len(s), 220)                 # 提示要短, 别把上下文撑大

    def test_str_matches_repr(self):
        img = self._img()
        self.assertEqual(str(img), repr(img))

    def test_data_and_type_are_unchanged(self):
        """只改显示, 不改数据: 下游无需适配。"""
        img = self._img(10, 20, 3)
        img[3, 4] = (1, 2, 3)
        self.assertIsInstance(img, np.ndarray)
        self.assertEqual(img.dtype, np.uint8)
        self.assertEqual(img.shape, (10, 20, 3))
        self.assertEqual(tuple(img[3, 4]), (1, 2, 3))
        # numpy 运算照旧
        self.assertEqual(int((img > 0).sum()), 3)
        self.assertEqual(img[1:3, 1:3].shape, (2, 2, 3))

    def test_grayscale_shape_is_described(self):
        self.assertIn('100x50x1', repr(self._img(50, 100, 1)))

    def test_shot_returns_the_hinting_subclass(self):
        """shot() 本身要返回子类, 否则白改。"""
        png = _tiny_png()
        with patch.object(droid, '_get', return_value=png), \
             patch.object(droid, '_black_check', lambda *a: None):
            out = droid.shot()
        self.assertIsInstance(out, droid._shot_img_cls())
        self.assertIn('print() cannot show an image', repr(out))

    def test_shot_with_path_still_returns_the_path(self):
        """path 给出的契约不变(返回路径字符串), 不能被子类改动破坏。"""
        import tempfile, os
        png = _tiny_png()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.png')
            with patch.object(droid, '_get', return_value=png), \
                 patch.object(droid, '_black_check', lambda *a: None):
                out = droid.shot(path=p)
            self.assertEqual(out, p)
            self.assertTrue(os.path.exists(p))


class OcrTypeCheckTest(unittest.TestCase):
    """ocr/ocr_text 的报错必须说清"该传什么 + 手上是什么 + 怎么改"。"""

    def _engine(self):
        return lambda img: [('box', 'text', 0.9)]

    def test_ndarray_passes_through_untouched(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        with patch.object(droid, '_ocr_engine', self._engine):
            out = droid.ocr(img)
        self.assertEqual(out, [('box', 'text', 0.9)])

    def test_pil_image_gets_an_actionable_message(self):
        class FakePIL:                     # 有 .crop 而无 ndarray 接口 = PIL 形态
            def crop(self, box): return self

        with self.assertRaises(TypeError) as cm:
            droid.ocr(FakePIL())
        msg = str(cm.exception)
        self.assertIn('needs a BGR ndarray', msg)
        self.assertIn('PIL Image', msg)
        self.assertIn('img[y1:y2, x1:x2]', msg)      # 给出正确写法
        self.assertIn('img.crop', msg)               # 点出它错在哪

    def test_path_string_gets_an_actionable_message(self):
        with self.assertRaises(TypeError) as cm:
            droid.ocr_text('/sdcard/x.png')
        msg = str(cm.exception)
        self.assertIn('needs a BGR ndarray', msg)
        self.assertIn('do not read files', msg)

    def test_other_types_still_rejected_with_the_kind_named(self):
        for bad in (None, 42, {'a': 1}):
            with self.assertRaises(TypeError) as cm:
                droid.ocr(bad)
            self.assertIn(type(bad).__name__, str(cm.exception))

    def test_ocr_text_also_checks(self):
        with self.assertRaises(TypeError):
            droid.ocr_text('nope')


def _tiny_png():
    """最小合法 PNG(4x4 纯色), 用 PIL 现造, 不靠手写 base64(写错一个字符 imdecode 就返回 None)。"""
    import numpy as np
    from PIL import Image as _PIL
    import io as _io
    buf = _io.BytesIO()
    _PIL.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(buf, format='PNG')
    return buf.getvalue()


if __name__ == '__main__':
    unittest.main()
