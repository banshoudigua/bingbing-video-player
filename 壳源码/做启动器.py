# -*- coding: utf-8 -*-
r"""
生成三个双击启动器（.bat）

为什么用 Python 生成而不是直接写文件：
    .bat 必须同时满足「CRLF 换行 + GBK(936) 编码」，否则 cmd 会：
      · 按 CRLF 解析行边界 → 只有 LF 时行首字符被吞
        （setlocal 被当成 cal 执行、cd /d 整段消失）
      · 按 GBK 解码 → 存成 UTF-8 时中文全乱
    而 Write 类工具产出的是 LF + UTF-8，且中文可能被替换成 '?'（不可逆）。
    所以这里用 Python 精确控字节：先拼文本，统一换行成 CRLF，再 encode('gbk')。

生成的文件：
    设为默认打开方式.bat      → 冰冰播放器.exe --设为默认
    恢复原默认打开方式.bat    → 冰冰播放器.exe --恢复默认
    查看当前默认打开方式.bat  → 冰冰播放器.exe --查状态
    启动冰冰播放器.bat        → 项目内启动器（用 %~dp0 取路径，必须留在项目目录）
    冰冰播放器.bat            → 桌面启动器（路径写死，可放桌面 / 任务栏）

后两个是 2026-09-18 收进来的：那两个 bat 原先不是本脚本生成的，
但它们的编码要求一模一样，收进来统一管理，改一次重跑就行。
"""

import os

# 生成出来的「桌面版」冰冰播放器.bat 里会把路径写死成这个。
# 克隆到本地后，先按你的实际位置改这一行，再重跑本脚本，
# 生成的桌面启动器才指得对地方。
播放器目录 = r"D:\你的路径\冰冰播放器"
本目录 = os.path.dirname(os.path.abspath(__file__))


# ---------------- 公共段落 ----------------

def 头(标题, 说明行):
    """每个 bat 开头那一段注释 + setlocal + cd，样式跟项目里既有的 bat 保持一致"""
    段 = []
    段.append("@echo off")
    段.append("setlocal")
    段.append("")
    段.append("rem ============================================================")
    段.append("rem  冰冰播放器 · " + 标题)
    段.append("rem")
    for 行 in 说明行:
        段.append(("rem  " + 行).rstrip())
    段.append("rem")
    段.append("rem  【编码说明】本文件必须是 GBK / ANSI 编码 + CRLF 换行。")
    段.append("rem    若另存为 UTF-8 或改成 LF 换行，cmd 会因多字节解码错乱")
    段.append("rem    而吞掉行首字符，中文也会乱码。")
    段.append("rem    中文 Windows 的 cmd 默认代码页就是 936，不需要加 chcp。")
    段.append("rem ============================================================")
    段.append("")
    段.append('cd /d "%~dp0"')
    段.append("")
    段.append('set "EXE=%~dp0冰冰播放器.exe"')
    段.append("")
    段.append('if not exist "%EXE%" (')
    段.append("    echo.")
    段.append("    echo [错误] 找不到主程序：")
    段.append("    echo        %EXE%")
    段.append("    echo.")
    段.append("    echo 可能原因：项目目录被移动或重命名了。")
    段.append("    echo 解决办法：把本文件放回 冰冰播放器.exe 所在目录再双击。")
    段.append("    echo.")
    段.append("    pause")
    段.append("    exit /b 1")
    段.append(")")
    段.append("")
    return 段


def 尾(提示行, 开关):
    段 = []
    for 行 in 提示行:
        段.append(("echo " + 行).rstrip())
    段.append("")
    段.append('start "" "%EXE%" ' + 开关)
    段.append("")
    段.append("exit /b 0")
    段.append("")
    return 段


# ---------------- 三个启动器 ----------------

设为默认 = 头("设为默认打开方式", [
    "双击本文件会做两件事：",
    "  1. 把「冰冰播放器」登记成 Windows 认可的默认应用条目",
    "     （登记后，设置 → 默认应用 里搜「冰冰播放器」能搜到，",
    "       并且有一个「设置默认值」按钮，点一次 17 种视频格式全设好）",
    "  2. 打开系统的「默认应用」设置页",
    "",
    "【为什么最后还要手动点一下】",
    "  本机 Windows 11 25H2 实测：真正生效的那份默认关联带一套",
    "  我们算不出来的校验值。第三方脚本硬写进注册表会被系统判定为篡改，",
    "  反而会把那个格式的关联整个弄坏（连原本的默认程序一起丢）。",
    "  所以脚本只能负责「把程序登记好、把设置页打开」，",
    "  最后那一下必须由人在系统界面里完成 —— 那是 Windows 唯一承认的途径。",
]) + 尾([
    "正在登记「冰冰播放器」为默认应用...",
    "",
    "稍等会弹出结果窗口，并自动打开系统的「默认应用」设置页。",
    "在设置页里搜「冰冰播放器」，点一次「设置默认值」即可全部设好。",
    "",
], "--设为默认")

恢复默认 = 头("恢复原默认打开方式", [
    "双击本文件会把默认关联还原成改动之前的样子。",
    "",
    "它依据的是「设为默认」时自动存下的备份文件：",
    "  _默认关联备份.json（在播放器目录下）",
    "那份备份记录的是「第一次设默认之前」每个格式原本的默认程序，",
    "之后不会被覆盖，所以可以反复还原。",
    "",
    "【同样要在设置页里点一下】",
    "  原因跟「设为默认」一样：本机真正生效的默认关联钥匙",
    "  带一套脚本算不出来的校验值，硬写会被系统做废。",
    "  所以本文件还原完注册表后会自动打开设置页，",
    "  你在那一项里把不想给的格式改回原程序即可。",
]) + 尾([
    "正在按备份还原默认关联...",
    "",
    "稍等会弹出结果窗口，并自动打开系统的「默认应用」设置页。",
    "",
], "--恢复默认")

查状态 = 头("查看当前默认打开方式", [
    "双击本文件会弹一个窗口，列出 17 种视频格式",
    "「双击之后实际会用谁打开」。",
    "",
    "这个数不是读注册表读出来的，而是直接问 Windows 外壳本身",
    "（AssocQueryString）—— 跟双击文件时走的是同一套判断，",
    "而且不会启动任何程序，看一眼没有副作用。",
    "",
    "标 ★ 的就是当前由冰冰播放器接管。",
    "如果某个格式显示「无关联」，双击它会弹「选取应用」，",
    "随便选一次程序并勾「始终」，系统就会重写一份合法关联，即可修好。",
    "",
    "排查问题时也看 冰冰播放器壳.log，里面每一步都有记录。",
]) + 尾([
    "正在查询各格式当前实际生效的默认程序...",
    "",
], "--查状态")


# ---------------- 播放器本体启动器（两个）----------------
#
# 这两个 bat 是拿来「打开播放器」的，跟上面三个「管关联」的不是一回事，
# 结构差别较大（要查浏览器、拼 file:// 地址），所以单独拼。
#
# 2026-09-18 起它们的启动参数都加了 --incognito：
#   目的是不在 Chrome 里留下 file:// 浏览历史（实测过，见 壳.py 里的注释）。

def 不留痕说明段():
    """两个播放器启动器共用的一段说明"""
    return [
        "rem  【不留痕】本播放器刻意不记任何东西：",
        "rem    · 不记播放列表 —— 每次打开都是现扫的，上次那份会被清掉",
        "rem    · 不记音量、不记播放列表面板的展开状态",
        "rem    · 不自动播放上次的视频",
        "rem    · 浏览器以无痕模式启动，不在 Chrome 里留下 file:// 浏览历史",
    ]


def 浏览器查找段():
    """两个播放器启动器共用的「找浏览器 → 拼地址 → 启动」这一段"""
    return [
        "rem ---- 按优先级查找浏览器 ----",
        'set "BROWSER="',
        r'if exist "C:\Program Files\Google\Chrome\Application\chrome.exe"                          set "BROWSER=C:\Program Files\Google\Chrome\Application\chrome.exe"',
        r'if not defined BROWSER if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"',
        r'if not defined BROWSER if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"     set "BROWSER=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"',
        r'if not defined BROWSER if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" set "BROWSER=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"',
        r'if not defined BROWSER if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe"  set "BROWSER=C:\Program Files\Microsoft\Edge\Application\msedge.exe"',
        "",
        "rem ---- 找不到浏览器就交给系统默认程序 ----",
        "if not defined BROWSER (",
        "    echo [提示] 没有找到 Chrome 或 Edge，改用系统默认浏览器打开。",
        '    start "" "%PLAYER%"',
        "    exit /b 0",
        ")",
        "",
        "rem ---- 反斜杠换成正斜杠，拼成 file:/// 地址 ----",
        r'set "URLPATH=%PLAYER:\=/%"',
        "",
        "rem 启动参数说明：",
        "rem   --incognito                          无痕启动，不在 Chrome 里留浏览历史",
        "rem   --app=...                            以应用模式打开（无地址栏 / 标签页）",
        "rem   --autoplay-policy=no-user-gesture-required  允许自动开始播放",
        "rem   --allow-file-access-from-files       允许 file:// 页面读取本地文件。",
        "rem     不加这个参数时，往窗口里拖文件夹会读不出来",
        "rem     （2026-09-17 实测：entry.file() 会报 EncodingError）。",
        r'start "" "%BROWSER%" --incognito --app="file:///%URLPATH%" --window-size=1280,720 --autoplay-policy=no-user-gesture-required --allow-file-access-from-files',
        "",
        "exit /b 0",
    ]


项目版 = [
    "@echo off",
    "setlocal",
    "",
    "rem ============================================================",
    "rem  冰冰播放器 · 项目内启动器",
    "rem",
    "rem  与桌面版「冰冰播放器.bat」的区别：",
    "rem    这个用 %~dp0 取路径，必须留在项目目录里；",
    "rem    桌面版是路径写死的，可以放到桌面 / 任务栏 / 开始菜单。",
    "rem",
    "rem  双击后会发生什么：",
    "rem    · 直接双击（没拖东西）→ 播放器以空状态打开，不带出上次的列表",
    "rem    · 拖了文件 / 文件夹到本图标上 → 扫描那个目录并列出里面的视频",
    "rem",
] + 不留痕说明段() + [
    "rem",
    "rem  【编码说明】本文件必须以 GBK / ANSI 编码保存 + CRLF 换行。",
    "rem  若另存为 UTF-8 或改成 LF 换行，cmd 会因多字节解码错乱而",
    "rem  解析不了下面的中文文件名。中文 Windows 的 cmd 默认代码页",
    "rem  就是 936，所以这里不需要也不应该加 chcp。",
    "rem",
    "rem  用系统已有的 Chrome / Edge 以「应用模式 + 无痕」打开播放器：",
    "rem    · 没有地址栏、没有标签页，外观就是一个独立播放器",
    "rem    · 复用系统浏览器内核，不额外打包一份 Chromium",
    "rem    · 无痕的代价：不能复用已在运行的 Chrome 进程，会另起一个实例，",
    "rem      内存比「复用进程」时多一点。这是「不留痕」必须付的成本。",
    "rem ============================================================",
    "",
    'cd /d "%~dp0"',
    "",
    'set "PAGEDIR=%~dp0"',
    'set "PLAYER=%~dp0冰冰播放器.html"',
    "",
    'if not exist "%PLAYER%" (',
    "    echo.",
    "    echo [错误] 找不到播放器主程序：",
    "    echo        %PLAYER%",
    "    echo.",
    "    pause",
    "    exit /b 1",
    ")",
    "",
    "rem ---- 生成播放列表 _播放列表.js ----",
    "rem 拖到本文件图标上启动时 %1 就是被拖进来的路径；直接双击时 %1 为空。",
    "rem   · 有路径 → 扫那个目录（给的是文件就扫它所在目录，并自动播它）",
    "rem   · 没路径 → _扫描.ps1 会写一份空清单，把上次的列表清掉",
    "rem 扫描交给独立的 ps1：bat 里嵌套引号加中文路径的转义几乎没法维护。",
    r'if not exist "%PAGEDIR%\_扫描.ps1" goto NO_SCAN',
    "",
    r'powershell -NoProfile -ExecutionPolicy Bypass -File "%PAGEDIR%\_扫描.ps1" -Target "%~1" -PlayerDir "%PAGEDIR%"',
    "goto SCAN_DONE",
    "",
    ":NO_SCAN",
    "echo [提示] 未找到 _扫描.ps1，本次跳过播放列表处理。",
    "",
    ":SCAN_DONE",
    "",
] + 浏览器查找段()


桌面版 = [
    "@echo off",
    "setlocal",
    "",
    "rem ============================================================",
    "rem  冰冰播放器 · 桌面启动器（路径写死版）",
    "rem",
    "rem  本文件适合放在桌面 / 任务栏 / 开始菜单，双击即开播放器。",
    "rem  与项目内「启动冰冰播放器.bat」的区别：",
    "rem    项目内那个用 %~dp0 取路径，必须留在项目目录里；",
    "rem    这个是路径写死的，可以放到任何位置。",
    "rem  所以项目目录一旦移动，请同步改下面的 PLAYER / PAGEDIR 变量。",
    "rem",
    "rem  双击后会发生什么：",
    "rem    · 直接双击（没拖东西）→ 播放器以空状态打开，不带出上次的列表",
    "rem    · 拖了文件 / 文件夹到本图标上 → 扫描那个目录并列出里面的视频",
    "rem",
] + 不留痕说明段() + [
    "rem",
    "rem  【编码说明】本文件必须是 GBK / ANSI 编码 + CRLF 换行。",
    "rem  若另存为 UTF-8 或改成 LF 换行，cmd 会因多字节解码错乱",
    "rem  而吞掉行首字符，中文路径也会乱码。",
    "rem  中文 Windows 的 cmd 默认代码页就是 936，这里不需要也不应该加 chcp。",
    "rem",
    "rem  用系统已有的 Chrome / Edge 以「应用模式 + 无痕」打开播放器：",
    "rem    · 没有地址栏、没有标签页，外观就是一个独立播放器",
    "rem    · 复用系统浏览器内核，不额外打包一份 Chromium",
    "rem    · 无痕的代价：不能复用已在运行的 Chrome 进程，会另起一个实例，",
    "rem      内存比「复用进程」时多一点。这是「不留痕」必须付的成本。",
    "rem ============================================================",
    "",
    "rem ---- 播放器主程序位置（写死，项目移动后改这里）----",
    'set "PLAYER=' + 播放器目录 + r'\冰冰播放器.html"',
    'set "PAGEDIR=' + 播放器目录 + '"',
    "",
    "rem ---- 固定片库目录（可选）----",
    "rem 不设就留空：双击本文件时不会扫描任何目录，播放器以空状态打开。",
    'rem 想固定扫某个片库就填进去，例如：set "LIBDIR=D:\\片库"',
    "rem 拖文件 / 文件夹到本文件图标上时，优先用被拖进来的路径。",
    'set "LIBDIR="',
    "",
    'if not exist "%PLAYER%" (',
    "    echo.",
    "    echo [错误] 找不到播放器主程序：",
    "    echo        %PLAYER%",
    "    echo.",
    "    echo 可能原因：项目目录被移动或重命名了。",
    "    echo 解决办法：右键本文件 - 编辑，把上面的路径改成实际位置。",
    "    echo.",
    "    pause",
    "    exit /b 1",
    ")",
    "",
    "rem ---- 生成播放列表 _播放列表.js ----",
    "rem 扫描目标优先级：",
    "rem   1) 拖到本文件图标上的 文件 / 文件夹（%1）",
    "rem   2) 上面设定的固定片库 LIBDIR",
    "rem   3) 都没有时：_扫描.ps1 会写一份空清单，把上次的列表清掉",
    "rem 扫描交给独立的 ps1：bat 里嵌套引号加中文路径的转义几乎没法维护。",
    r'if not exist "%PAGEDIR%\_扫描.ps1" goto NO_SCAN',
    "",
    'set "SCANTARGET=%~1"',
    'if "%SCANTARGET%"=="" set "SCANTARGET=%LIBDIR%"',
    "",
    r'powershell -NoProfile -ExecutionPolicy Bypass -File "%PAGEDIR%\_扫描.ps1" -Target "%SCANTARGET%" -PlayerDir "%PAGEDIR%"',
    "goto SCAN_DONE",
    "",
    ":NO_SCAN",
    "echo [提示] 未找到 _扫描.ps1，本次跳过播放列表处理。",
    "",
    ":SCAN_DONE",
    "",
] + 浏览器查找段()


要写的 = [
    ("设为默认打开方式.bat", 设为默认),
    ("恢复原默认打开方式.bat", 恢复默认),
    ("查看当前默认打开方式.bat", 查状态),
    ("启动冰冰播放器.bat", 项目版),
    ("冰冰播放器.bat", 桌面版),
]


# ---------------- 落盘 + 自检 ----------------

结果 = []
结果.append("=" * 84)
结果.append("生成双击启动器（CRLF + GBK 字节自检）")
结果.append("=" * 84)
结果.append("")

全过 = True
for 文件名, 段 in 要写的:
    文本 = "\r\n".join(段)
    # 统一换行：先归一成 \n 再整体换 CRLF，避免出现 \r\r\n
    文本 = 文本.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    字节 = 文本.encode("gbk")

    路径 = os.path.join(播放器目录, 文件名)
    with open(路径, "wb") as f:
        f.write(字节)

    # ---- 自检 ----
    with open(路径, "rb") as f:
        实际 = f.read()
    CR数 = 实际.count(13)
    LF数 = 实际.count(10)
    有BOM = 实际[:3] == b"\xef\xbb\xbf"
    问号数 = 实际.count(63)          # 0x3F
    头六字节 = 实际[:6]

    好 = (CR数 == LF数) and (not 有BOM) and (头六字节 == b"@echo ")
    if not 好:
        全过 = False

    结果.append(">>> " + 文件名)
    结果.append("    路径      = %s" % 路径)
    结果.append("    字节      = %d" % len(实际))
    结果.append("    CR / LF   = %d / %d   %s"
                % (CR数, LF数, "✓ 相等" if CR数 == LF数 else "★ 不等，cmd 会吞行首字符"))
    结果.append("    开头 6 字节 = %r   %s"
                % (头六字节, "✓" if 头六字节 == b"@echo " else "★ 不对"))
    结果.append("    BOM       = %s" % ("★ 有（不该有）" if 有BOM else "无 ✓"))
    结果.append("    '?' 个数  = %d   %s"
                % (问号数, "✓ 没有中文丢失" if 问号数 == 0 else "★ 有中文被替换成 ?"))
    # 再按 GBK 解一遍，确认中文读得回来
    文本回读 = 实际.decode("gbk")
    第一行注释 = [行 for 行 in 文本回读.splitlines() if "冰冰播放器 ·" in 行]
    结果.append("    GBK 回读  = %s" % (第一行注释[0] if 第一行注释 else "★ 读不到标题行"))
    结果.append("")

结果.append("=" * 84)
结果.append("结果：%s" % ("全部启动器合格 ✓" if 全过 else "★ 有文件不合格，看上面带 ✗ 的行"))
结果.append("=" * 84)

输出 = "\n".join(结果)
print(输出)
with open(os.path.join(本目录, "_启动器自检.txt"), "w", encoding="utf-8-sig") as f:
    f.write(输出)
