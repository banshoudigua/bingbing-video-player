# -*- coding: utf-8 -*-
"""
冰冰播放器 —— 本地小桥（EXE 与播放页面之间的通道）

为什么需要它：
    播放页面是 file:// 打开的普通网页。浏览器安全限制下，网页既不能删除
    磁盘上的文件，也不能调起资源管理器 —— 这是硬限制，绕不过去。
    所以这些「碰磁盘」的动作全部交给外壳：外壳在 127.0.0.1 上开一个只给
    本机看的小服务，页面通过它下发指令。

安全上做死三件事：
    1. 只监听 127.0.0.1（外部机器连不上，也不会被同网段扫到）
    2. 每次启动生成一个随机口令，页面必须带上才认（端口 + 口令一起，
       通过 --app 地址的 #bbp= 片段传给页面）
    3. 能操作的路径卡死在「本次扫描的那个目录」里的视频文件 ——
       它不是通用删除接口，别的路径一律拒

生命周期：
    页面每 15 秒 ping 一次当心跳。窗口一关，心跳停 → 45 秒后自动收摊退出。
    这样不会留一个不死进程在后台（和「关掉重开不留痕迹」的口径一致）。

本文件与 壳.py 同目录，被 壳.py 延迟 import（见 冰冰播放器.spec 的 hiddenimports）。
"""

import ctypes
import json
import os
import secrets
import subprocess
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ---------------- 常量 ----------------

不显窗口 = 0x08000000     # CREATE_NO_WINDOW：起子进程时不闪黑框

心跳超时秒 = 45           # 页面这么久没来请求，就认定窗口关了
首次连接宽限 = 90         # 启动后这么久还没人连，认定页面没起来
最长寿命秒 = 12 * 3600    # 兜底上限，避免任何意外情况下留一个不死进程

# 起桥时把服务器对象存这儿，停止() 才有东西可以关。
# 用列表而不是单个变量，是因为要在函数里改到它（和 壳.py 的 干跑标志 一个道理）。
_服务器 = []

# 允许操作的文件类型 = _扫描.ps1 会写进清单的全部扩展名（$playable + $unsupported）。
# 【2026-10-13 加音频】原来只有视频，现在把常见音频也纳进来。
# 口径必须与 _扫描.ps1 和页面里那两张表保持一致，否则会出现
# 「列表里看得到这个文件，小桥却拒绝操作」的割裂感。
允许扩展名 = {
    # 内核能播的（视频）
    ".mp4", ".m4v", ".webm", ".mov", ".ogv",
    # 内核能播的（音频）
    ".mp3", ".m4a", ".m4b", ".aac", ".wav", ".flac",
    ".ogg", ".oga", ".opus", ".weba",
    # 常见但内核不支持（视频）
    ".mkv", ".avi", ".rmvb", ".rm", ".wmv", ".flv", ".ts", ".m2ts",
    ".vob", ".3gp", ".f4v", ".asf", ".mpg", ".mpeg", ".divx", ".xvid", ".swf",
    # 常见但内核不支持（音频）
    ".wma", ".ape", ".aiff", ".aif", ".amr", ".mka", ".mid", ".ac3", ".dts",
}

# ---- 回收站（Shell 文件操作）----
# 用 SHFileOperationW 而不是 os.remove：
#   os.remove 是彻底删除，误按 DEL 就找不回来了；
#   SHFileOperationW 带 FOF_ALLOWUNDO 就是「丢进回收站」，用户能自己还原。
# 注意：不能用 IFileOperation（那是 COM，本机安全策略禁 COM 实例化）。
FO_DELETE          = 3
FOF_SILENT         = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO      = 0x0040    # 进回收站
FOF_NOERRORUI      = 0x0400    # 出错别弹系统框，我们自己回报


class 文件操作结构(ctypes.Structure):
    """对应 shellapi.h 的 SHFILEOPSTRUCTW"""

    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


# ---------------- 碰磁盘的三件事 ----------------


def 移到回收站(路径):
    """把文件丢进回收站。返回 (成功, 说明)"""
    结构 = 文件操作结构()
    结构.hwnd = None
    结构.wFunc = FO_DELETE
    # pFrom 要求「以两个 \\0 结尾」的字符串列表。
    # create_unicode_buffer 自己会补一个 \\0，所以这里手动再加一个，
    # 拼出来正好是 "路径\\0\\0" —— 少一个的话这个调用会直接失败。
    缓冲 = ctypes.create_unicode_buffer(路径 + "\0")
    结构.pFrom = ctypes.cast(缓冲, wintypes.LPCWSTR)
    结构.pTo = None
    结构.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

    返回码 = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(结构))

    # 【判据】不能只看返回码，要看「文件还在不在」。
    #
    # 2026-10-13 实测（沙盒外，读回收站 $I 记录核对过）：
    #   带 FOF_ALLOWUNDO 删除 → 返回码 = 2，但文件确实消失、且回收站记录 +1，
    #   新增那条记录的原始路径正是被删的文件。
    #   也就是说：删成功了，返回码却是非 0 —— 文档说的「返回 0 才成功」在这台机器上不成立。
    #   要是照文档写，页面会收到「删除失败」，文件删了却不从列表里消失，很别扭。
    # 所以以文件存在与否为准，返回码只留在提示文字里供排查。
    if os.path.exists(路径):
        return False, "没能删掉（系统返回码 %d，文件仍在，可能正被别的程序占用）" % 返回码

    if 结构.fAnyOperationsAborted:
        return True, "文件已移走，但系统报告操作被中止（返回码 %d），建议确认一下回收站" % 返回码

    return True, "已移入回收站"


def 打开并选中(路径):
    """打开资源管理器，并把这个文件选中高亮"""
    # 这里刻意用「命令字符串」而不是参数列表：
    # explorer.exe 是自己解析命令行的（不走 CRT 的 argv 规则），它的文档写法就是
    #   explorer /select,"带空格的完整路径"
    # 交给参数列表的话 Python 会把整个 /select,C:\... 当成一个 token 再套一层引号，
    # 多一层引号 explorer 认不认全看它心情 —— 不如按文档原样给。
    subprocess.Popen('explorer.exe /select,"%s"' % 路径, creationflags=不显窗口)


def 读文件信息(路径):
    """读一份「此刻磁盘上」的真实数据，供页面展示"""
    状态 = os.stat(路径)

    # 文件属性：只读 / 隐藏 / 系统 / 存档
    ctypes.windll.kernel32.GetFileAttributesW.restype = ctypes.c_uint32
    属性码 = ctypes.windll.kernel32.GetFileAttributesW(路径)
    属性名 = []
    if 属性码 & 0x01:
        属性名.append("只读")
    if 属性码 & 0x02:
        属性名.append("隐藏")
    if 属性码 & 0x04:
        属性名.append("系统")
    if 属性码 & 0x20:
        属性名.append("存档")

    # 注意：Windows 上 st_ctime 是「创建时间」，不是 Unix 那种 inode 变更时间
    return {
        "exists": True,
        "path": 路径,
        "size": 状态.st_size,
        "ctime": int(状态.st_ctime * 1000),
        "mtime": int(状态.st_mtime * 1000),
        "attrs": "、".join(属性名) if 属性名 else "普通",
    }


# ---------------- 小桥本体 ----------------


class 桥处理器(BaseHTTPRequestHandler):
    """http.server 每次请求都新建一个实例，所以共享状态一律挂在类属性上"""

    口令 = ""
    允许目录 = ""
    写日志回调 = None
    最后请求 = 0.0
    请求数 = 0

    # 关掉默认的访问日志：exe 是无窗口的，写 stderr 谁也看不见，纯属浪费
    def log_message(self, 格式, *参数):
        return

    def _回(self, 状态码, 数据):
        """统一出口：JSON + CORS。页面是 file:// 来的（来源是 null），必须放行"""
        正文 = json.dumps(数据, ensure_ascii=False).encode("utf-8")
        self.send_response(状态码)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(正文)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # Chrome 的「私有网络访问」检查：网页访问本机地址时要显式放行
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(正文)

    def _记一笔(self):
        """每个请求都刷新心跳时刻 —— 外层靠它判断窗口还在不在"""
        桥处理器.最后请求 = time.time()
        桥处理器.请求数 += 1

        # 第一个请求来自谁，记一笔。
        #
        # 为什么只记第一个：日志是个一直往后追加的文件，每个 15 秒的心跳都写一条就没法看了。
        # 它的用处是排查「小桥起来了，但页面上那几个按钮点了没反应」——
        # 看一眼这条就知道页面到底有没有连上来，还是只有别的什么东西在戳这个端口。
        if 桥处理器.请求数 == 1:
            来客 = self.headers.get("User-Agent") or "（没带 User-Agent）"
            self._日志("小桥收到第一个请求，来自：" + 来客[:90])

    def _日志(self, 话):
        if 桥处理器.写日志回调:
            桥处理器.写日志回调(话)

    def do_OPTIONS(self):
        """预检请求（Chrome 抽查私有网络访问时会发）"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        解析 = urlparse(self.path)
        查询 = parse_qs(解析.query)
        路径 = 查询.get("p", [""])[0]
        口令 = 查询.get("t", [""])[0]
        接口 = 解析.path
        self._记一笔()

        # 【2026-10-13 收紧】心跳也照样要口令。
        #
        # 原先这里留了个口子：接口是 /ping 就直接放行，理由是「它没有任何操作能力」。
        # 但那个口子可以当「端口扫描探针」用 —— 随便哪个网页都能试着扫本地端口，
        # 哪个端口回 200 就说明「这人正在用冰冰播放器」。功能上一分钱不值，索性收紧。
        # 页面本来就是带着口令来 ping 的（见 冰冰播放器.html 的 bridgeCall），
        # 卡上口令不影响任何功能。
        if 口令 != 桥处理器.口令:
            self._日志("小桥：口令不对，拒绝 %s" % 接口)
            self._回(403, {"ok": False, "reason": "口令不对"})
            return

        if 接口 == "/ping":
            self._回(200, {"ok": True, "at": int(time.time() * 1000)})
            return

        if 接口 == "/reveal":
            通过, 理由 = 校验路径(路径)
            if not 通过:
                self._日志("小桥：拒绝定位 %s（%s）" % (路径, 理由))
                self._回(400, {"ok": False, "reason": 理由})
                return
            打开并选中(路径)
            self._日志("小桥：已在资源管理器中定位 %s" % 路径)
            self._回(200, {"ok": True, "reason": "已打开所在文件夹"})
            return

        if 接口 == "/delete":
            通过, 理由 = 校验路径(路径)
            if not 通过:
                self._日志("小桥：拒绝删除 %s（%s）" % (路径, 理由))
                self._回(400, {"ok": False, "reason": 理由})
                return
            成功, 说明 = 移到回收站(路径)
            self._日志("小桥：删除 %s → %s" % (路径, 说明))
            self._回(200 if 成功 else 500, {"ok": 成功, "reason": 说明})
            return

        if 接口 == "/info":
            if not 路径 or not os.path.isfile(路径):
                self._回(400, {"ok": False, "reason": "文件不存在"})
                return
            self._日志("小桥：读文件信息 %s" % 路径)
            self._回(200, {"ok": True, "info": 读文件信息(路径)})
            return

        self._回(404, {"ok": False, "reason": "没有这个接口"})


def 校验路径(路径):
    """能不能对这个路径动手。返回 (通过, 理由)

    小桥是个手上握着「删文件」能力的东西，范围必须卡死：
    只认本次扫描目录底下的、扩展名在允许名单里的、确实存在的文件。
    """
    if not 路径:
        return False, "没有给出路径"

    绝对 = os.path.abspath(路径)

    if not os.path.isfile(绝对):
        return False, "文件不存在"

    if os.path.splitext(绝对)[1].lower() not in 允许扩展名:
        return False, "不是播放器认的媒体文件，小桥不管"

    根 = 桥处理器.允许目录
    if not 根:
        return False, "这次启动没有扫描目录"

    # 前缀比对：把盘符大小写差异统一掉（Windows 路径不区分大小写）
    前缀 = 根.rstrip("\\").lower() + "\\"
    if not 绝对.lower().startswith(前缀):
        return False, "不在本次扫描的目录里，小桥不管"

    return True, ""


def _绑并运行(结果, 允许目录, 写日志回调):
    """在子线程里绑端口并开始服务

    刻意放在子线程：万一端口绑不上，异常只死在这个线程里，主流程照样能把
    视频打开 —— 宁可这一次没有小桥，也不能因此打不开视频。
    """
    口令 = secrets.token_hex(16)

    桥处理器.允许目录 = os.path.abspath(允许目录) if 允许目录 else ""
    桥处理器.口令 = 口令
    桥处理器.写日志回调 = 写日志回调
    桥处理器.最后请求 = time.time()
    桥处理器.请求数 = 0

    服务器 = ThreadingHTTPServer(("127.0.0.1", 0), 桥处理器)   # 端口交给系统挑空闲的
    端口 = 服务器.server_address[1]
    _服务器.append(服务器)
    结果.append((端口, 口令))

    if 写日志回调:
        写日志回调("小桥已就绪：127.0.0.1:%d（只允许操作 %s 底下的视频）" % (端口, 桥处理器.允许目录))

    服务器.serve_forever(poll_interval=0.5)


def 启动(允许目录, 写日志回调):
    """起桥。返回 (端口, 口令)；没起来就返回 (0, "")"""
    结果 = []
    线程 = threading.Thread(target=_绑并运行, args=(结果, 允许目录, 写日志回调))
    线程.daemon = True
    线程.start()

    # 等它绑好（最多 1.5 秒）。绑成功会立刻有值，正常情况一瞬间就返回
    for _ in range(30):
        if 结果:
            break
        time.sleep(0.05)

    if not 结果:
        if 写日志回调:
            写日志回调("小桥没能启动：端口绑定失败。本次没有删除 / 打开文件夹能力")
        return 0, ""

    return 结果[0][0], 结果[0][1]


def 停止():
    """主动把桥关掉。返回 True 表示真的有关掉东西

    正常使用时用不上它：窗口一关，等待页面结束() 就让整个进程退出了，
    端口跟着进程一起释放。
    但干跑和自动化测试需要能主动收摊 —— 否则会留一个端口占着，
    下一次测试再起桥就在后台堆了一串没人管的监听。
    """
    if not _服务器:
        return False
    服务器 = _服务器[0]
    _服务器[:] = []
    服务器.shutdown()        # 让 serve_forever 那圈循环退出来（最多等一个 poll_interval）
    服务器.server_close()
    return True


def 等待页面结束(写日志回调):
    """守着心跳，直到页面没了再收摊

    三个退出条件：
      · 有请求过、且已经心跳超时秒没动静  → 窗口关了，正常收摊
      · 一直没请求过、超过首次连接宽限    → 页面没起来，收摊
      · 超过最长寿命秒                    → 兜底收摊
    """
    起点 = time.time()

    while True:
        time.sleep(2)
        现在 = time.time()
        空闲 = 现在 - 桥处理器.最后请求

        if 桥处理器.请求数 > 0 and 空闲 > 心跳超时秒:
            if 写日志回调:
                写日志回调("页面已关闭（%.0f 秒没有请求），小桥收摊" % 空闲)
            return "页面已关闭"

        if 桥处理器.请求数 == 0 and (现在 - 起点) > 首次连接宽限:
            if 写日志回调:
                写日志回调("页面一直没连上来（浏览器没起来？），小桥收摊")
            return "页面未连接"

        if (现在 - 起点) > 最长寿命秒:
            if 写日志回调:
                写日志回调("小桥到寿命上限，收摊")
            return "到寿命上限"
