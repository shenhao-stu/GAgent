# Offline voice / 离线语音

Hold the microphone button to speak (at least 300 ms), release to transcribe,
or slide up to cancel. Recognition supports Chinese and English, runs locally,
and appends to the current draft. Review the text before sending. A recording is
limited to 60 seconds and is cancelled when the app leaves the foreground.
System text-to-speech remains available separately.

按住麦克风说话（至少 300 毫秒），松开识别，上滑取消；中英文转写追加到当前草稿，
不会自动发送。单次最多 60 秒，应用退到后台会取消录音。系统朗读继续保留。

The first press downloads about 82 MB. Retry after a failed download; partial files
can resume. Once ready, grant microphone access and hold again. No voice endpoint,
token or model-provider account is required. Old streaming voice fields are removed
from stored and imported integration profiles; other service settings are retained.

首次点击下载约 82 MB 模型；失败可重试并续传。就绪后允许麦克风，再次按住即可使用。
独立在线语音配置已移除，升级仅删除其旧字段，保留其他组件配置。

## Sources and privacy

- Engine: [sherpa-onnx 2.0.1](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1),
  Apache-2.0. The build verifies the static ONNX Runtime AAR digest and retains arm64 JNI.
- Model: [Paraformer small](https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-small-2024-03-09/tree/63ddc3cd0f2810b68289a7b3876e62ef5d53d6df),
  converted by the sherpa maintainer from [this ModelScope source](https://www.modelscope.cn/models/crazyant/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8358-onnx/summary).
  Weights are not redistributed in the APK. The conversion repository does not
  declare a separate model license; do not infer its terms from sherpa's code license.
- Fixed revision, sizes and SHA-256 hashes are in `VoiceModel.kt`. Redirects must
  remain HTTPS; downloaded bytes are bounded and verified before native loading.
- Downloading contacts the public asset hosts. Microphone audio is held in memory
  for local recognition, never sent to a speech server or written as a recording by
  this feature. Sending the resulting draft uses the user's chosen model provider.

代码许可不等于模型许可；模型来源与校验值明确记录，APK 不分发权重。下载会连接公开资源站，
语音识别本身不上传音频。用户主动发送转写后的草稿时，仍会调用其所选模型服务。
