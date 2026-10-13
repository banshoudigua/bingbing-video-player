# 冰冰播放器 —— 播放列表扫描器
#
# 扫描指定目录下的视频文件，生成 _播放列表.js 供播放器读取。
#
# 为什么单独做成 .ps1 而不是写在 bat 里：
#   1) bat 里嵌套引号 + 中文 + 路径转义极易出错，几乎不可能维护
#   2) PowerShell 脚本存成 UTF-8 BOM 后能正确处理中文路径
#
# 本文件必须保存为 UTF-8 with BOM（无 BOM 时 PowerShell 5.1
# 会按 GBK 解读，中文路径直接乱码）。

param(
  [string]$Target    = "",   # 拖到 bat 图标上的路径（文件或文件夹），空表示只扫描播放器目录
  [string]$PlayerDir = ""    # 播放器所在目录
)

# 去掉路径结尾的反斜杠：bat 用 %~dp0 传进来时会带一个尾巴，
# 不去掉的话 Join-Path 拼出来是双反斜杠，虽然 Windows 能认但不干净
$PlayerDir = $PlayerDir.TrimEnd('\')
if ($Target -ne "") { $Target = $Target.TrimEnd('\') }

# 播放器内核能直接播的格式（视频 + 音频）。
# 【口径必须与播放器页面里的 EXT_PLAYABLE 完全一致，改一处就要改另一处】
#   视频：mp4 / m4v / webm / mov / ogv
#   音频：mp3 / m4a / m4b / aac / wav / flac / ogg / oga / opus / weba
$playable = @('.mp4', '.m4v', '.webm', '.mov', '.ogv',
              '.mp3', '.m4a', '.m4b', '.aac', '.wav', '.flac',
              '.ogg', '.oga', '.opus', '.weba')

# 常见但内核解析不了、只作展示的格式（列表里会置灰标「不支持」）。
# 【口径必须与页面里的 EXT_UNSUPPORTED 一致】
#
# 2026-10-13 修正：以前 .flv 挂在 $playable 里，但 Chromium 早就播不了 FLV
# （那是 Flash 时代的东西），页面端本来就把它判成「不支持」。
# 两处口径不一致会让「可播放 N 个」的统计虚高，现在统一挪到 $unsupported。
$unsupported = @('.mkv', '.avi', '.rmvb', '.rm', '.wmv', '.flv',
                 '.ts', '.m2ts', '.vob', '.3gp', '.f4v', '.asf',
                 '.mpg', '.mpeg', '.divx', '.xvid', '.swf',
                 '.wma', '.ape', '.aiff', '.aif', '.amr', '.mka',
                 '.mid', '.ac3', '.dts')

# ---- 决定扫描目录 ----
# 注意 $scanDir 初始为空 —— 不再默认成播放器目录（原因见下面的「不留痕」分支）
$scanDir  = ""
$playFile = ""

if ($Target -ne "" -and (Test-Path -LiteralPath $Target)) {
  if (Test-Path -LiteralPath $Target -PathType Container) {
    # 拖进来的是文件夹：直接扫它
    $scanDir = (Resolve-Path -LiteralPath $Target).Path
  } else {
    # 拖进来的是文件：扫它所在的文件夹，并记下文件名让播放器开播它。
    #
    # 这里用 .NET 的 Path 方法而不是 Split-Path：
    # Split-Path 把 -LiteralPath 与 -Parent / -Leaf 组合使用时，
    # PowerShell 5.1 会报「无法使用指定的命名参数解析参数集」直接失败
    $scanDir  = [System.IO.Path]::GetDirectoryName($Target)
    $playFile = [System.IO.Path]::GetFileName($Target)
  }
}

# ---- 没有有效目标 → 生成一份空清单，把上次的内容覆盖掉 ----
#
# 【不留痕 · 关键】以前这里 $scanDir 默认就是播放器自己所在目录，
# 于是每次打开播放器都会带出上次那个目录的视频列表，看起来就是「历史记录」。
# 现在改成写一份空清单：播放器打开时读到空的，就是干干净净一个空播放器。
if ($scanDir -eq "") {
  # 【时区坑 · 2026-09-18 实测踩到】取 Unix 毫秒必须用 DateTimeOffset。
  # 若写成 [datetime]'1970-01-01 00:00:00Z' 再与 UtcNow 相减，
  # PowerShell 5.1 会把带 Z 的字符串解析成**本地时间**（Kind=Local，值变成 08:00:00），
  # 相减后算出来的时间戳整体少 8 小时（东八区偏移）。
  # 后果：播放器把刚生成的清单判成「8 小时前的过期数据」直接丢掉。
  $nowMs     = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  $jsonEmpty = '{"dir":"","play":"","stamp":' + $nowMs + ',"files":[]}'
  $jsEmpty    = 'window.BB_PLAYLIST=' + $jsonEmpty + ';'
  $outEmpty   = Join-Path $PlayerDir '_播放列表.js'
  [System.IO.File]::WriteAllText($outEmpty, $jsEmpty,
                                 (New-Object System.Text.UTF8Encoding $true))
  Write-Output "没有指定视频目标：已生成空播放列表（清掉上次的内容）"
  Write-Output "清单已写入: $outEmpty"
  exit 0
}

# 走到这里 $scanDir 一定非空（空的情况上面已经 exit 了），只需确认目录确实存在
if (-not (Test-Path -LiteralPath $scanDir)) {
  Write-Output "扫描目录不存在，跳过生成播放列表：$scanDir"
  exit 0
}

# ---- 扫描视频文件 ----
# 限制 3 层深度：够覆盖「按剧集分子文件夹」的常见结构，
# 又不至于在超大目录里扫上几十秒
$exts = $playable + $unsupported
$found = @(Get-ChildItem -LiteralPath $scanDir -Recurse -Depth 3 -File -ErrorAction SilentlyContinue |
           Where-Object { $exts -contains $_.Extension.ToLower() })

# ---- 组装清单 ----
# 【时区坑】这里同样不能用 [datetime]'1970-01-01 00:00:00Z'（见上面空清单分支的说明）。
# 用 DateTimeOffset 才没有 Kind / 时区歧义。
$epoch = [DateTimeOffset]'1970-01-01T00:00:00Z'
$list  = @()

foreach ($f in $found) {
  # 统一转成绝对 file:// 直链。
  # 用 System.Uri 而不是手工拼字符串：路径里的中文、空格、# 都会被正确编码，
  # 手工拼极容易漏掉某个字符导致播放器取不到文件
  $u = [System.Uri]::new($f.FullName).AbsoluteUri

  # 时间统一成毫秒时间戳（UTC），避免时区差异。
  # 注意：要先把 DateTime 转成 DateTimeOffset 再相减 ——
  # DateTime 直接减 DateTimeOffset 会按本地时区做隐式转换，
  # 算出来又会偏 8 小时（同上面那个坑）
  $ct = [int64](([DateTimeOffset]$f.CreationTime.ToUniversalTime()  - $epoch).TotalMilliseconds)
  $mt = [int64](([DateTimeOffset]$f.LastWriteTime.ToUniversalTime() - $epoch).TotalMilliseconds)

  $list += [PSCustomObject]@{
    n = $f.Name        # 文件名
    s = [int64]$f.Length
    c = $ct            # 创建时间
    m = $mt            # 修改时间
    u = $u             # file:// 直链
  }
}

# ---- 输出成 js ----
# stamp：这份清单的生成时刻（Unix 毫秒，UTC）。
# 播放器靠它判断清单是不是「本次刚扫描出来的」——
# 旧清单会被直接丢掉，这样重开播放器就不会冒出上次那个目录的列表。
$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

$obj = [PSCustomObject]@{
  dir   = $scanDir
  play  = $playFile
  stamp = $stamp
  files = $list
}

$json = $obj | ConvertTo-Json -Depth 5 -Compress

# PowerShell 5.1 的坑：ConvertTo-Json 在数组「只有一个元素」时会把数组退化成
# 单个对象（files 从 [...] 变成 {...}）。这事在字符串层面没法安全修正，
# 所以播放器端做了兼容：发现 files 不是数组就自己包一层。
# 这里只兜住彻底没输出的极端情况。
if ([string]::IsNullOrEmpty($json)) {
  $json = '{"dir":"","play":"","stamp":' + $stamp + ',"files":[]}'
}

$js = 'window.BB_PLAYLIST=' + $json + ';'
$outPath = Join-Path $PlayerDir '_播放列表.js'

# 带 BOM 写出：ConverterTo-Json 不会把中文转义成 \uXXXX，
# 所以必须靠 BOM 让浏览器明确知道这是 UTF-8
[System.IO.File]::WriteAllText($outPath, $js, (New-Object System.Text.UTF8Encoding $true))

$playCnt = @($found | Where-Object { $playable -contains $_.Extension.ToLower() }).Count
$badCnt  = $found.Count - $playCnt

Write-Output "扫描目录: $scanDir"
Write-Output "可播放  : $playCnt 个"
Write-Output "不支持  : $badCnt 个"
Write-Output "清单已写入: $outPath"
