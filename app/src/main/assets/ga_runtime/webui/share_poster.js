/* GenericAgent share-poster renderer: pure layout/HTML, usable in WebView and Node tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GASharePoster = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MIN_AR = 0.55;
  const MAX_AR = 2.6;
  const CANVAS_W = 1080;
  // 唯一强调色(SHARE_POSTER.DESIGN.md colors.primary)。刊物风暖纸上的一点铅印朱砂:
  // 只用于三处证物标记(证明点/元信息方块/GA 下划线), 绝不进正文与按钮。
  // 曾用 iOS 系统绿 #30D158 —— 那是端外来色, 与 app 自身单色墨黑(--acc:#1d1d1f)体系冲突。
  const SPOT = "#C4501E";
  const SPOT_WASH = "rgba(196,80,30,.20)";

  function boundedRatio(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0
      ? Math.max(MIN_AR, Math.min(MAX_AR, n))
      : fallback;
  }

  function layout(viewAr, shotAr) {
    const fallback = 16 / 9;
    const canvasAr = boundedRatio(viewAr, boundedRatio(shotAr, fallback));
    const screenAr = boundedRatio(shotAr, canvasAr);
    const mode = canvasAr < 0.85
      ? "wide"
      : canvasAr < 1.35 ? "book" : "portrait";
    const profile = {
      portrait: {
        deviceWidth: 270, framePad: 10, frameRadius: 34,
        screenRadius: 26, titleSize: 40, titleLines: 2, qrSize: 92
      },
      book: {
        deviceWidth: 420, framePad: 7, frameRadius: 22,
        screenRadius: 16, titleSize: 32, titleLines: 2, qrSize: 84
      },
      wide: {
        deviceWidth: 460, framePad: 5, frameRadius: 14,
        screenRadius: 9, titleSize: 28, titleLines: 3, qrSize: 76
      }
    }[mode];
    const dense = mode === "wide" && canvasAr < 0.62;
    if (dense) Object.assign(profile, { titleSize: 24, qrSize: 64 });
    return Object.assign({
      mode,
      dense,
      canvasAr,
      canvasW: CANVAS_W,
      canvasH: Math.round(CANVAS_W * canvasAr),
      screenAr
    }, profile);
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function duration(ms) {
    const total = Math.round(Number(ms) / 1000);
    if (!Number.isFinite(total) || total <= 0) return "";     // 亚秒/无效: 不渲染, 不谎报 "00:00"
    const s = total % 60, m = Math.floor(total / 60) % 60, h = Math.floor(total / 3600);
    const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
    return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;   // ≥1h 进位为 H:MM:SS, 不封顶成假 99:xx
  }

  function darkColor(value) {
    const color = String(value || "");
    let match = color.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    let red, green, blue;
    if (match) {
      red = +match[1]; green = +match[2]; blue = +match[3];
    } else {
      match = color.match(/^#([0-9a-f]{6})/i);
      if (!match) return true;
      const packed = parseInt(match[1], 16);
      red = packed >> 16 & 255; green = packed >> 8 & 255; blue = packed & 255;
    }
    return .299 * red + .587 * green + .114 * blue < 140;
  }

  function statusBar(width, foreground, camera, now) {
    const right = width - 16;
    return '<svg class="statusBar" viewBox="0 0 ' + width + ' 26" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
      + '<text x="20" y="17.5" font-size="12.5" font-weight="600" font-family="system-ui,sans-serif" fill="' + foreground + '">' + esc(now) + '</text>'
      + (camera ? '<circle cx="' + (width / 2).toFixed(1) + '" cy="13" r="4.8" fill="#050506"/>' : '')
      + [0, 1, 2, 3].map(function (index) {
        return '<rect x="' + (right - 64 + index * 5) + '" y="' + (16 - 3 * index)
          + '" width="3.4" height="' + (4 + 3 * index) + '" rx="1" fill="' + foreground
          + '"' + (index === 3 ? ' opacity=".35"' : '') + '/>';
      }).join("")
      + '<path d="M' + (right - 42) + ' 13.5a9 9 0 0 1 12 0" stroke="' + foreground + '" stroke-width="1.7" fill="none" stroke-linecap="round"/>'
      + '<circle cx="' + (right - 36) + '" cy="18.6" r="1.5" fill="' + foreground + '"/>'
      + '<rect x="' + (right - 26) + '" y="8" width="20" height="10.5" rx="3" stroke="' + foreground + '" stroke-width="1.3" fill="none"/>'
      + '<rect x="' + (right - 24.2) + '" y="9.8" width="12.5" height="6.9" rx="1.6" fill="' + foreground + '"/>'
      + '</svg>';
  }

  function html(options) {
    options = options || {};
    const info = options.info || {};
    const copy = options.copy || {};
    const profile = layout(info.viewAr, info.shotAr);
    const viewportWidth = Math.max(280, Number(info.vw) || 360);
    const screenshotAr = boundedRatio(info.shotAr, profile.screenAr);
    const statusRelative = 26 / viewportWidth;
    const totalScreenAr = screenshotAr + statusRelative;
    const innerWidth = profile.deviceWidth - profile.framePad * 2;
    const deviceHeight = Math.round(innerWidth * totalScreenAr + profile.framePad * 2);
    const statusPercent = +(statusRelative / totalScreenAr * 100).toFixed(3);
    const foreground = darkColor(info.scrBg) ? "#F7F7FA" : "#121316";
    const title = esc(info.title || "").replace(/GA/, '<span class="ga">GA</span>');
    const meta = [
      Number(info.steps) > 0 ? Number(info.steps) + " " + esc(copy.stepsWord || "steps") : "",
      duration(info.ms),
      esc(copy.autoWord || ""),
      profile.mode === "wide" ? "" : esc(info.autotip || "")
    ].filter(Boolean).join('<span class="sep">·</span>');
    const screenshot = options.shotImg
      ? '<img class="shot" src="' + esc(options.shotImg) + '" alt="">'
      : '<div class="standby"><i></i><b>AGENT DISPLAY · STANDBY</b><span>' + esc(copy.privacy || "") + '</span></div>';
    const qr = options.qrDataUrl
      ? '<img src="' + esc(options.qrDataUrl) + '" alt="">'
      : "";
    const layoutCss = profile.mode === "wide"
      ? 'grid-template-columns:minmax(0,36fr) minmax(0,64fr);grid-template-rows:auto minmax(0,1fr) auto;grid-template-areas:"mast mast" "copy hero" "foot hero";column-gap:calc(26*var(--u));padding:calc(22*var(--u)) calc(28*var(--u));'
      : profile.mode === "book"
        ? 'grid-template-columns:1fr;grid-template-rows:auto auto minmax(0,1fr) auto;grid-template-areas:"mast" "copy" "hero" "foot";padding:calc(24*var(--u)) calc(30*var(--u));'
        : 'grid-template-columns:1fr;grid-template-rows:auto auto minmax(0,1fr) auto;grid-template-areas:"mast" "copy" "hero" "foot";padding:calc(40*var(--u)) calc(40*var(--u)) calc(32*var(--u));';
    const variables = [
      "--device-w:" + profile.deviceWidth,
      "--device-h:" + deviceHeight,
      "--frame-pad:" + profile.framePad,
      "--frame-radius:" + profile.frameRadius,
      "--screen-radius:" + profile.screenRadius,
      "--title-size:" + profile.titleSize,
      "--title-lines:" + profile.titleLines,
      "--qr-size:" + profile.qrSize,
      "--status-pct:" + statusPercent + "%"
    ].join(";");

    return '<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      + '<style>'
      + '*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden}'
      + '.poster{' + variables + ';position:absolute;inset:0;display:grid;' + layoutCss
      + 'background:#F7F6F2;color:#121316;font-family:-apple-system,"SF Pro Display","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;-webkit-font-smoothing:antialiased}'
      + '.mast{grid-area:mast;display:flex;align-items:center;gap:calc(9*var(--u));padding-bottom:calc(12*var(--u));border-bottom:1px solid #121316}'
      + '.proofDot{width:calc(10*var(--u));height:calc(10*var(--u));border-radius:calc(3*var(--u));background:' + SPOT + ';flex:none}'
      + '.brand{font-size:calc(20*var(--u));font-weight:800;letter-spacing:-.02em}'
      + '.runTag{margin-left:auto;color:#666972;font:500 calc(9*var(--u))/1.4 "SF Mono",ui-monospace,monospace;letter-spacing:.12em;white-space:nowrap}'
      + '.copy{grid-area:copy;align-self:start;padding-top:calc(20*var(--u));min-width:0}'
      + '.headline{font-size:calc(var(--title-size)*var(--u));font-weight:750;line-height:1.12;letter-spacing:-.025em;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:var(--title-lines);overflow:hidden}'
      + '.headline .ga{position:relative;z-index:0}.headline .ga::after{content:"";position:absolute;z-index:-1;left:-.05em;right:-.05em;bottom:.02em;height:.28em;background:' + SPOT_WASH + '}'
      + '.meta{margin-top:calc(12*var(--u));display:flex;align-items:center;color:#3F4147;font:500 calc(9.5*var(--u))/1.4 "SF Mono",ui-monospace,monospace;letter-spacing:.10em}'
      + '.meta::before{content:"";width:calc(7*var(--u));height:calc(7*var(--u));background:' + SPOT + ';margin-right:calc(8*var(--u));flex:none}'
      + '.metaTxt{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sep{margin:0 calc(7*var(--u));color:#8A8C91}'
      // 舞台声明为尺寸容器, 机身才能用 cqw/cqh 同时参照两个轴。
      + '.deviceStage{grid-area:hero;min-width:0;min-height:0;display:flex;align-items:center;justify-content:center;padding:calc(16*var(--u)) 0;container-type:size}'
      // 尺寸不变量: 机身 = 能放进舞台的最大等比矩形, 两个轴都可收缩。
      // 旧写法 height:min(100%, device-h*u) 把竖屏机身钉死在绝对尺寸 —— 舞台明明还有余量,
      // 于是恒占高 72%/宽 59%, 四周全是死白(截图源本就是 1080 物理像素, 放大仍是降采样, 不掉质)。
      // 但「height:100% + aspect-ratio + max-width:100%」同样错: Chromium 在 max-width 夹紧宽度后
      // **不会**回算已确定的高度, 机身被压扁(wide/book 档实测变形 18~25%), .screen 比例随之偏离
      // totalScreenAr, 截图 contain 后留出大片实心暗带 —— 正是 DESIGN.md 明令禁止的 band/stretch。
      // 故取 width = min(舞台宽, 舞台高 × 宽高比), 高度由 aspect-ratio 派生: 恒不溢出、恒不变形。
      // 首行 width:100% 是不支持容器查询单位时的降级(整条 min() 在解析期失效即回退到它)。
      + '.device{position:relative;width:100%;width:min(100cqw,calc(100cqh * var(--device-w) / var(--device-h)));aspect-ratio:' + profile.deviceWidth + '/' + deviceHeight + ';border-radius:calc(var(--frame-radius)*var(--u));background:#17181C;border:1px solid rgba(255,255,255,.18);box-shadow:0 calc(20*var(--u)) calc(48*var(--u)) calc(-18*var(--u)) rgba(18,19,22,.38)}'
      // 内衬(bezel)用绝对定位的四边 inset 而非 padding: 百分比 padding 的基准是**包含块的宽度**
      // (CSS 2.1 §8.4) —— 即舞台宽, 不是机身宽, 用它算出的内衬会随舞台漂移(实测竖屏偏 29%、book 档偏 94%),
      // 反而把它本要消灭的暗边放大约 10 倍。绝对定位的 top/bottom 百分比基准是包含块的**高度**,
      // left/right 是宽度, 于是两个轴各自按机身自身尺寸取比例, content 比例恒等于 totalScreenAr(任意缩放皆精确)。
      + '.screen{position:absolute;top:calc(var(--frame-pad) / var(--device-h) * 100%);bottom:calc(var(--frame-pad) / var(--device-h) * 100%);left:calc(var(--frame-pad) / var(--device-w) * 100%);right:calc(var(--frame-pad) / var(--device-w) * 100%);overflow:hidden;border-radius:calc(var(--screen-radius)*var(--u));background:' + esc(info.scrBg || "#111214") + '}'
      + '.statusBar{position:absolute;z-index:2;inset:0 0 auto;width:100%;height:var(--status-pct);display:block}'
      + '.shot{position:absolute;left:0;right:0;top:var(--status-pct);width:100%;height:calc(100% - var(--status-pct));object-fit:contain;object-position:top center;display:block;background:' + esc(info.scrBg || "#111214") + '}'
      + '.standby{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:calc(8*var(--u));color:rgba(255,255,255,.55);font:500 calc(8*var(--u))/1.4 ui-monospace,monospace;letter-spacing:.16em}.standby i{width:calc(8*var(--u));height:calc(8*var(--u));border-radius:50%;background:' + SPOT + '}.standby span{opacity:.55}'
      + '.foot{grid-area:foot;display:flex;align-items:center;gap:calc(16*var(--u));border-top:1px solid #D8D6CF;padding-top:calc(14*var(--u));min-width:0}'
      + '.footCopy{flex:1;min-width:0}.hook{font-size:calc(15*var(--u));font-weight:700;line-height:1.3}.url{margin-top:calc(5*var(--u));color:#666972;font:500 calc(9*var(--u))/1.35 "SF Mono",ui-monospace,monospace;letter-spacing:.08em}.url b{color:#3F4147}'
      + '.qr{width:calc(var(--qr-size)*var(--u));height:calc(var(--qr-size)*var(--u));padding:calc(6*var(--u));border:1px solid #D8D6CF;border-radius:calc(10*var(--u));background:#FFFDF8;flex:none}.qr img{width:100%;height:100%;display:block;image-rendering:pixelated}'
      + '.poster--wide .mast{padding-bottom:calc(8*var(--u))}.poster--wide .copy{padding-top:calc(14*var(--u));padding-right:calc(4*var(--u))}.poster--wide .foot{align-self:end}.poster--wide .hook{font-size:calc(13*var(--u))}.poster--wide .url{font-size:calc(8*var(--u))}'
      + '.poster--dense .mast{padding-bottom:calc(6*var(--u))}.poster--dense .copy{padding-top:calc(10*var(--u))}.poster--dense .foot{padding-top:calc(8*var(--u));gap:calc(12*var(--u))}.poster--dense .hook{font-size:calc(11*var(--u))}.poster--dense .url{font-size:calc(7.5*var(--u));margin-top:calc(3*var(--u))}'
      + '.poster--book .copy{padding-top:calc(14*var(--u))}.poster--book .deviceStage{padding:calc(8*var(--u)) 0}.poster--book .foot{padding-top:calc(10*var(--u))}'
      + '</style></head><body>'
      + '<main class="poster poster--' + profile.mode + (profile.dense ? ' poster--dense' : '') + '">'
      + '<header class="mast"><span class="proofDot"></span><span class="brand">GenericAgent</span><span class="runTag">' + esc(copy.runTag || "") + '</span></header>'
      + '<section class="copy"><h1 class="headline">' + title + '</h1>' + (meta ? '<div class="meta"><span class="metaTxt">' + meta + '</span></div>' : '') + '</section>'
      + '<section class="deviceStage"><div class="device"><div class="screen">'
      + statusBar(viewportWidth, foreground, profile.mode !== "portrait", options.now || "")
      + screenshot + '</div></div></section>'
      + '<footer class="foot"><div class="footCopy"><div class="hook">' + esc(copy.hook || "") + '</div><div class="url"><b>' + esc(options.host || "") + '</b> — ' + esc(copy.urlLine || "") + '</div></div>'
      + '<div class="qr">' + qr + '</div></footer>'
      + '</main><script>document.documentElement.style.setProperty("--u",(document.documentElement.clientWidth/540)+"px");</scr' + 'ipt></body></html>';
  }

  return { layout, html };
});
