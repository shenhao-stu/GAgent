# 相册选图 SOP (album_select) — VLM 认图 + picker 单/多选

> 触发见 `modes_index`。在系统相册/图片选择器(PhotoPicker)里用视觉认出目标图并 tap 选中。

## 两条路(默认第一条)
- **首选·免授权(实测可用)**: 认屏上缩略图——开 picker → `shot` → `ask_vision` 认目标在第几格 → `ui_detect` 定位该格 → tap。缩略图够认大类内容。
- **高保真·需授权**: 读原图(`/sdcard/DCIM/...`)需「所有文件访问」(manifest 已声明但默认未授)。**未授时读 /sdcard 是 Permission denied，别假设能读真实路径**；需要就引导用户在「设置>应用>GAgent>所有文件访问」打开。

## 用法(屏上识别)
```python
import droid, time
# ask_vision 已由 code_run 预导入（droid.ask_vision，默认复用任务页当前模型）
def center(b): return ((b[0]+b[2])//2, (b[1]+b[3])//2)
img = droid.shot()                       # picker 已在前台、缩略图网格已出现
target = '用户要的那张'                    # 运行时换成真实描述，别发占位符
ans = ask_vision(img, f'相册缩略图网格从上到下、从左到右编号。哪张是「{target}」? 只回数字')
idx = int(''.join(c for c in ans if c.isdigit()) or 1) - 1
cells = [e for e in droid.ui_detect(img) if e.get('cls') in ('Image','Card') or e.get('type')=='icon']
rh = (min(e['bbox'][3]-e['bbox'][1] for e in cells)//2) or 100   # 行桶≈缩略图高，不写死像素
cells.sort(key=lambda e:(e['bbox'][1]//rh, e['bbox'][0]))
droid.tap(*center(cells[idx]['bbox']), human=True); time.sleep(0.6)
```
- 单选 tap 即返回(部分 picker 再点「完成」)；多选逐张 tap 出角标后点「添加(N)/确定」。
- 目标不在可见区 → `droid.scroll_view('down')` 翻页再认，别一屏死磕。
- 判成没成: picker 关闭回发起页、目标图已带入(`shot` 复核)；多选核计数。

## 注意
- picker 属系统 UI 用视觉，别 dump(隐私)；只选用户要的那张(几张)，不批量导出。
- 选中图发送/分享给他人走 phone_use §0.7 确认门；只用 picker 返回的 URI。
