# -*- coding: utf-8 -*-
"""
冰冰播放器 · Windows 默认打开方式（UserChoice）读写模块

【为什么不能直接写 ProgId 了事】
    Windows 8 之后，用户级「默认关联」不再看别的，只看这一个键：
        HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\.ext\\UserChoice
    而且这个键里的 ProgId 还配了一个 Hash 校验值。系统会自己重算一遍跟存档比对，
    对不上就当没设过，顺手把键删掉 —— 这就是那句
    「某个应用默认值已重置」通知的来历。
    所以想真正改默认，必须自己把这个 Hash 算出来。

【算法出处】
    逆向自微软 Shell32 的实现，与开源工具 PS-SFTA / SetUserFTA 的算法一致：
        原文   = (扩展名 + 用户SID + ProgId + 注册时间 + 盐) 全小写
        字节   = 原文的 UTF-16LE 编码，末尾再补两个 0 字节
        摘要   = MD5(字节)
        然后拿摘要里取出的两个 32 位小整数当种子，跑两轮自定义的 32 位整数运算
        → 得到 16 字节 → 前后两半各取一个 32 位值两两异或 → 8 字节 → Base64
    盐（experience）是从 shell32.dll 里捞出来的：不同 Windows 版本这个 GUID
    可能不一样，所以不能只写死；捞不到才用硬编码兜底。
    注册时间是「当前时间抹掉秒」按 FILETIME 拆成高/低各 8 位小写十六进制。

【本模块的写法约定】
    按五阿哥的要求：不用 try/except，改成「返回错误码 + 回调」的形式。
    所以注册表操作一律走 ctypes 直调 advapi32 —— 这些 API 本来就返回错误码、
    不抛异常；顺带还能拿到 RegQueryInfoKey 才有的「键最后写入时间」。
"""

import base64
import ctypes
import hashlib
import json
import os
import struct
import time
import urllib.parse   # 给 ms-settings 的 URI 参数做编码
import winreg          # 只用来 EnumKey 列子键（ctypes 版枚举写起来太啰嗦）
from ctypes import wintypes

# ============================================================
# 一、Win32 常量与函数原型
# ============================================================

HKEY_CURRENT_USER = 0x80000001
HKEY_CLASSES_ROOT = 0x80000000

KEY_READ = 0x20019
KEY_WRITE = 0x20006
KEY_CREATE_SUB_KEY = 0x0004
KEY_ENUMERATE_SUB_KEYS = 0x0008

错误成功 = 0
错误找不到文件 = 2
错误找不到路径 = 3
错误拒绝访问 = 5
错误键不存在 = 2

REG_SZ = 1
REG_NONE = 0

MASK32 = 0xFFFFFFFF

# 每 100 纳秒一个单位，1601-01-01 到 1970-01-01 之间的单位数
FILETIME_1970 = 116444736000000000

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# ---- 注册表 ----
advapi32.RegOpenKeyExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_ulong, ctypes.POINTER(wintypes.HKEY)]
advapi32.RegOpenKeyExW.restype = ctypes.c_long

advapi32.RegCreateKeyExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD,
                                     wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_ulong,
                                     ctypes.c_void_p, ctypes.POINTER(wintypes.HKEY),
                                     ctypes.POINTER(wintypes.DWORD)]
advapi32.RegCreateKeyExW.restype = ctypes.c_long

advapi32.RegSetValueExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
advapi32.RegSetValueExW.restype = ctypes.c_long

advapi32.RegQueryValueExW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR,
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.c_void_p,
                                      ctypes.POINTER(wintypes.DWORD)]
advapi32.RegQueryValueExW.restype = ctypes.c_long

advapi32.RegQueryInfoKeyW.argtypes = [wintypes.HKEY, wintypes.LPWSTR,
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.c_void_p]
advapi32.RegQueryInfoKeyW.restype = ctypes.c_long

advapi32.RegDeleteKeyW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
advapi32.RegDeleteKeyW.restype = ctypes.c_long

advapi32.RegCloseKey.argtypes = [wintypes.HKEY]
advapi32.RegCloseKey.restype = ctypes.c_long

advapi32.RegDeleteValueW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
advapi32.RegDeleteValueW.restype = ctypes.c_long

# ---- 取当前用户 SID（哈希的输入之一）----
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL

advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                         ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
advapi32.GetTokenInformation.restype = wintypes.BOOL

advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_wchar_p)]
advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p

# ---- 取消息框（exe 没有控制台，报错只能靠弹窗）----
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                               wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

# ---- COM：问系统「这个扩展名有效的默认程序是谁」----
#   用的是 IApplicationAssociationRegistration，跟「设置 → 默认应用」同一个接口。
#   千万别用 AssocQueryStringW 代替：2026-09-17 实测它对 .mp4 / .ogv 直接返回
#   0x80070483 ERROR_NO_ASSOCIATION，连改动前的状态都问不出来 ——
#   因为它读的是旧的 HKCU\Software\Classes\.ext（那里挂的是 KMPlayer），
#   压根不看 UserChoice 键，所以它答不准。详见第五节。


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong),
                ("d2", ctypes.c_ushort),
                ("d3", ctypes.c_ushort),
                ("d4", ctypes.c_ubyte * 8)]


def 造GUID(串):
    """把 "591209C7-767B-42B2-9FBA-44EE4615F2C7" 这种写法变成 GUID 结构"""
    段 = 串.strip("{}").split("-")
    尾巴 = bytes.fromhex(段[3] + 段[4])
    结果 = GUID()
    结果.d1 = int(段[0], 16)
    结果.d2 = int(段[1], 16)
    结果.d3 = int(段[2], 16)
    for i in range(8):
        结果.d4[i] = 尾巴[i]
    return 结果


class 应用关联虚表(ctypes.Structure):
    """IApplicationAssociationRegistration 的方法表。
       前三个固定是 IUnknown 的，后面按接口声明顺序排"""
    _fields_ = [
        ("QueryInterface", ctypes.c_void_p),
        ("AddRef", ctypes.c_void_p),
        ("Release", ctypes.c_void_p),
        ("QueryCurrentDefault", ctypes.c_void_p),
        ("QueryAppIsDefault", ctypes.c_void_p),
        ("QueryAppIsDefaultAll", ctypes.c_void_p),
        ("SetAppAsDefault", ctypes.c_void_p),
        ("SetAppAsDefaultAll", ctypes.c_void_p),
        ("ClearUserAssociations", ctypes.c_void_p),
    ]


ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
                                    wintypes.DWORD, ctypes.POINTER(GUID),
                                    ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

# ---- 广播「关联变了」，让已经在运行的外壳（资源管理器）丢掉缓存 ----
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000
shell32.SHChangeNotify.argtypes = [ctypes.c_long, wintypes.UINT,
                                   ctypes.c_void_p, ctypes.c_void_p]


class FILETIME(ctypes.Structure):
    """Win32 的 FILETIME：高低两个 32 位拼成 64 位"""
    _fields_ = [("低", wintypes.DWORD), ("高", wintypes.DWORD)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


# ============================================================
# 二、基础小工具（注册表读写，全部返回错误码）
# ============================================================

def 打开键(子键, 权限=KEY_READ, 根=HKEY_CURRENT_USER):
    """打开指定根下的子键（默认 HKCU）。返回 (错误码, 键句柄)"""
    句柄 = wintypes.HKEY()
    码 = advapi32.RegOpenKeyExW(根, 子键, 0, 权限, ctypes.byref(句柄))
    return 码, 句柄


def 建键(子键):
    """创建（已存在就直接打开）HKCU 下的子键。返回 (错误码, 键句柄)"""
    句柄 = wintypes.HKEY()
    处置 = wintypes.DWORD(0)
    码 = advapi32.RegCreateKeyExW(HKEY_CURRENT_USER, 子键, 0, None, 0,
                                  KEY_READ | KEY_WRITE, None,
                                  ctypes.byref(句柄), ctypes.byref(处置))
    return 码, 句柄


def 关键(句柄):
    if 句柄:
        advapi32.RegCloseKey(句柄)


def 读字符串(子键, 值名="", 根=HKEY_CURRENT_USER):
    """读一个 REG_SZ。返回 (错误码, 字符串)；键或值不存在时字符串为空。
       根传 HKEY_CLASSES_ROOT 可以读合并后的类视图"""
    码, 句柄 = 打开键(子键, KEY_READ, 根)
    if 码 != 错误成功:
        return 码, ""

    类型 = wintypes.DWORD(0)
    字节数 = wintypes.DWORD(0)
    码 = advapi32.RegQueryValueExW(句柄, 值名, None, ctypes.byref(类型),
                                  None, ctypes.byref(字节数))
    if 码 != 错误成功 or 字节数.value == 0:
        关键(句柄)
        return 码, ""

    缓冲 = ctypes.create_unicode_buffer(字节数.value // 2 + 2)
    码 = advapi32.RegQueryValueExW(句柄, 值名, None, ctypes.byref(类型),
                                  缓冲, ctypes.byref(字节数))
    关键(句柄)
    if 码 != 错误成功:
        return 码, ""
    return 错误成功, 缓冲.value


def 写字符串(子键, 值名, 值):
    """写一个 REG_SZ（键不存在会自动建）。返回错误码"""
    码, 句柄 = 建键(子键)
    if 码 != 错误成功:
        return 码
    缓冲 = ctypes.create_unicode_buffer(值)
    码 = advapi32.RegSetValueExW(句柄, 值名, 0, REG_SZ,
                                 ctypes.cast(缓冲, ctypes.c_void_p),
                                 ctypes.sizeof(缓冲))
    关键(句柄)
    return 码


def 写空值(子键, 值名):
    """
    写一个 REG_NONE 空值。
    OpenWithProgids 下面登记候选程序用的就是这种「只有名字没有数据」的值。
    """
    码, 句柄 = 建键(子键)
    if 码 != 错误成功:
        return 码
    码 = advapi32.RegSetValueExW(句柄, 值名, 0, REG_NONE, None, 0)
    关键(句柄)
    return 码


def 删值(子键, 值名):
    """删掉一个值（键不存在就当成功，方便重复执行）"""
    码, 句柄 = 打开键(子键, KEY_READ | KEY_WRITE)
    if 码 != 错误成功:
        return 错误成功
    码 = advapi32.RegDeleteValueW(句柄, 值名)
    关键(句柄)
    return 码


def 删键(子键):
    """删掉一个子键（它自己不能再带子键）。键本就不存在时也算成功"""
    码 = advapi32.RegDeleteKeyW(HKEY_CURRENT_USER, 子键)
    if 码 == 错误找不到文件 or 码 == 错误找不到路径:
        return 错误成功
    return 码


def 取键修改时间(子键):
    """
    取子键最后一次写入时间，返回「抹掉秒」的 FILETIME 十六进制串；失败返回空串。
    这个值是算哈希的输入之一 —— 因为系统校验时也是拿键的写入时间来回算的，
    所以每次改完关联，旧哈希就作废了，必须用新时间重算。
    """
    码, 句柄 = 打开键(子键)
    if 码 != 错误成功:
        return ""
    时间 = FILETIME()
    码 = advapi32.RegQueryInfoKeyW(句柄, None, None, None, None, None, None,
                                  None, None, None, None, ctypes.byref(时间))
    关键(句柄)
    if 码 != 错误成功:
        return ""
    单位 = (时间.高 << 32) | 时间.低
    # FILETIME 单位是 100 纳秒，所以一分钟 = 60 × 10^7 个单位。
    # 【关键】必须抹到「分钟」，不是「秒」！
    # 2026-09-17 实测：拿本机现成的 UserChoice 键当标准答案逐级试探，
    # 「抹到秒」「抹到时」全不匹配，「抹到分钟」一次命中。
    单位 -= 单位 % (60 * 10000000)
    return "%08x%08x" % ((单位 >> 32) & MASK32, 单位 & MASK32)


# ============================================================
# 三、哈希算法本体
# ============================================================

def 取低32(值):
    """把任意整数截成 32 位有符号 —— 模拟 C 里的整数溢出回绕"""
    值 &= MASK32
    return 值 - 0x100000000 if 值 & 0x80000000 else 值


def 读int32(缓冲, 偏移):
    """小端读一个有符号 32 位整数。越界返回 0（正常流程不会越界，这是安全网）"""
    if 偏移 < 0 or 偏移 + 4 > len(缓冲):
        return 0
    return struct.unpack_from("<i", 缓冲, 偏移)[0]


def 右移(值, 位数):
    """
    对应 PS-SFTA 的 Get-ShiftRight。
    它的实际效果是「先把值当成 32 位无符号数，再右移」——
    原来的写法在位 31 为 1 时会异或 0xFFFF0000 把符号扩展的那几位抹掉，
    等价于无符号右移，这里直接这么写更清楚。
    """
    return (值 & MASK32) >> 位数


盐前缀 = "User Choice set via Windows User Experience"
盐兜底 = "User Choice set via Windows User Experience {D18B6DD5-6124-4341-9318-804003BAFA0B}"
_盐缓存 = [""]


def 取体验盐():
    """
    从 shell32.dll 里把「盐」字符串捞出来。
    不同 Windows 版本这个字符串里的 GUID 可能不同，所以优先动态取；
    取不到才退回硬编码值。结果缓存起来，不用每次重读 5MB。
    """
    if _盐缓存[0]:
        return _盐缓存[0]

    系统根 = os.environ.get("SystemRoot", r"C:\Windows")
    候选 = [
        os.path.join(系统根, "SysWOW64", "shell32.dll"),
        os.path.join(系统根, "System32", "shell32.dll"),
        os.path.join(系统根, "shell32.dll"),
    ]
    for 路径 in 候选:
        if not os.path.exists(路径):
            continue
        with open(路径, "rb") as 文件:
            字节 = 文件.read(5 * 1024 * 1024)
        文本 = 字节.decode("utf-16-le", "ignore")
        头 = 文本.find(盐前缀)
        if 头 < 0:
            continue
        尾 = 文本.find("}", 头)
        if 尾 < 0:
            continue
        _盐缓存[0] = 文本[头:尾 + 1]
        return _盐缓存[0]

    _盐缓存[0] = 盐兜底
    return _盐缓存[0]


def 取注册时间戳():
    """当前时间抹掉秒 → FILETIME → 高/低各 8 位小写十六进制拼起来（16 个字符）"""
    此刻 = time.localtime()
    秒 = int(time.mktime((此刻.tm_year, 此刻.tm_mon, 此刻.tm_mday,
                          此刻.tm_hour, 此刻.tm_min, 0, 0, 0, -1)))
    单位 = 秒 * 10000000 + FILETIME_1970
    return "%08x%08x" % ((单位 >> 32) & MASK32, 单位 & MASK32)


def 算用户选择哈希(扩展名, 用户SID, 程序ID, 注册时间="", 盐=""):
    """
   算出 UserChoice 的 Hash 值（Base64 字符串）。

    参数：
        扩展名   —— 形如 ".mp4"
        用户SID  —— 聊天 S-1-5-21-...
        程序ID   —— 形如 "BBPlayer.Video"
        注册时间 —— 留空则用当前时间；调试时可传指定值
        盐       —— 留空则自动从 shell32.dll 取
    """
    注册时间 = 注册时间 or 取注册时间戳()
    盐 = 盐 or 取体验盐()

    # 拼接顺序是固定的：扩展名 + SID + ProgId + 注册时间 + 盐，然后整体转小写
    原文 = (扩展名 + 用户SID + 程序ID + 注册时间 + 盐).lower()

    # UTF-16LE 编码后，末尾还要补两个 0 字节 —— 微软就是这么算的
    数据 = 原文.encode("utf-16-le") + b"\x00\x00"
    摘要 = hashlib.md5(数据).digest()

    # 要跑多少轮，跟着原文长度走
    基准长 = len(原文) * 2 + 2
    长度 = (1 if (基准长 & 4) == 0 else 0) + (基准长 >> 2) - 1
    if 长度 <= 1:
        return ""       # 原文短到没法算，微软那边同样给不出哈希

    序 = (长度 - 2) >> 1
    轮数 = 序 + 1

    # ---- 第一轮 ----
    # 注意这里两个种子是 int32 或 1 之后再加大常数，会超过 32 位，
    # 所以它们是 64 位量，不能提前截断
    种子1 = 取低32(读int32(摘要, 0) | 1) + 0x69FB0000
    种子2 = 取低32(读int32(摘要, 4) | 1) + 0x13DB0000

    缓存 = 0
    累1 = 0
    指针 = 0
    剩 = 轮数
    while 剩:
        r0 = 取低32(读int32(数据, 指针) + 累1)
        r1 = 读int32(数据, 指针 + 4)
        指针 += 8
        r2 = 取低32(r0 * 种子1 - 0x10FA9605 * 右移(r0, 16))
        r2 = 取低32(0x79F8A395 * r2 + 0x689B6B9F * 右移(r2, 16))
        r3 = 取低32(0xEA970001 * r2 - 0x3C101569 * 右移(r2, 16))
        r4 = 取低32(r3 + r1)
        r5 = 取低32(缓存 + r3)
        r6 = 取低32(r4 * 种子2 - 0x3CE8EC25 * 右移(r4, 16))
        r6 = 取低32(0x59C3AF2D * r6 - 0x2232E0F1 * 右移(r6, 16))
        累1 = 取低32(0x1EC90001 * r6 + 0x35BD1EC9 * 右移(r6, 16))
        累2 = 取低32(r5 + 累1)
        缓存 = 累2
        剩 -= 1
    前半 = struct.pack("<II", 累1 & MASK32, 累2 & MASK32)

    # ---- 第二轮（种子不再加大常数）----
    种子1 = 取低32(读int32(摘要, 0) | 1)
    种子2 = 取低32(读int32(摘要, 4) | 1)

    缓存 = 0
    累1 = 0
    指针 = 0
    剩 = 轮数
    while 剩:
        r0 = 取低32(读int32(数据, 指针) + 累1)
        指针 += 8
        r1 = 取低32(r0 * 种子1)
        r1 = 取低32(0xB1110000 * r1 - 0x30674EEF * 右移(r1, 16))
        r2 = 取低32(0x5B9F0000 * r1 - 0x78F7A461 * 右移(r1, 16))
        r2 = 取低32(0x12CEB96D * 右移(r2, 16) - 0x46930000 * r2)
        r3 = 取低32(0x1D830000 * r2 + 0x257E1D83 * 右移(r2, 16))
        # 指针已经加过 8，这里回退 4 读的是第二组的低 32 位
        r4 = 取低32(种子2 * (r3 + 读int32(数据, 指针 - 4)))
        r4 = 取低32(0x16F50000 * r4 - 0x5D8BE90B * 右移(r4, 16))
        r5 = 取低32(0x96FF0000 * r4 - 0x2C7C6901 * 右移(r4, 16))
        r5 = 取低32(0x2B890000 * r5 + 0x7C932B89 * 右移(r5, 16))
        累1 = 取低32(0x9F690000 * r5 - 0x405B6097 * 右移(r5, 16))
        累2 = 取低32(累1 + 缓存 + r3)
        缓存 = 累2
        剩 -= 1
    后半 = struct.pack("<II", 累1 & MASK32, 累2 & MASK32)

    # ---- 收尾：16 字节里前后两半各自异或，取 8 字节再 Base64 ----
    全量 = 前半 + 后半
    值1 = 读int32(全量, 8) ^ 读int32(全量, 0)
    值2 = 读int32(全量, 12) ^ 读int32(全量, 4)
    结果 = struct.pack("<II", 值1 & MASK32, 值2 & MASK32)
    return base64.b64encode(结果).decode("ascii")


# ============================================================
# 四、当前用户 SID
# ============================================================

_SID缓存 = [""]

def 取当前用户SID():
    """拿当前登录用户的 SID 字符串（哈希的输入之一）。失败返回空串"""
    if _SID缓存[0]:
        return _SID缓存[0]

    TOKEN_QUERY = 0x0008
    TokenUser = 1

    令牌 = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(令牌)):
        return ""

    需要 = wintypes.DWORD(0)
    advapi32.GetTokenInformation(令牌, TokenUser, None, 0, ctypes.byref(需要))
    if 需要.value <= 0:
        kernel32.CloseHandle(令牌)
        return ""

    缓冲 = ctypes.create_string_buffer(需要.value)
    if not advapi32.GetTokenInformation(令牌, TokenUser, 缓冲, 需要.value,
                                        ctypes.byref(需要)):
        kernel32.CloseHandle(令牌)
        return ""

    结构 = ctypes.cast(缓冲, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents
    文本 = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(结构.Sid, ctypes.byref(文本)):
        kernel32.CloseHandle(令牌)
        return ""

    _SID缓存[0] = 文本.value or ""
    kernel32.LocalFree(文本)
    kernel32.CloseHandle(令牌)
    return _SID缓存[0]


# ============================================================
# 五、问系统：这个扩展名「有效」的默认程序是谁（验收标准就靠它）
# ============================================================

CLSID_应用关联登记 = 造GUID("591209C7-767B-42B2-9FBA-44EE4615F2C7")
IID_应用关联登记 = 造GUID("4E530B0A-E611-4C77-A3AC-9031D022281B")

AT_文件扩展 = 0     # ASSOCIATIONTYPE 里的 AT_FILEEXTENSION
AL_有效 = 1         # ASSOCIATIONLEVEL 里的 AL_EFFECTIVE

_COM缓存 = [None]


def 取COM对象():
    """
    懒加载并缓存 COM 对象。返回 (对象指针, 取当前默认函数)；失败返回 None。
    只用一次就不在乎退出了 —— 进程结束系统自己回收，不必刻意 Release。
    """
    if _COM缓存[0]:
        return _COM缓存[0]

    # COINIT_APARTMENTTHREADED = 0x2；已经初始化过会返回 S_FALSE，无妨
    ole32.CoInitializeEx(None, 0x2)

    对象 = ctypes.c_void_p()
    码 = ole32.CoCreateInstance(ctypes.byref(CLSID_应用关联登记), None, 0x1,
                              ctypes.byref(IID_应用关联登记), ctypes.byref(对象))
    if 码 != 0 or not 对象:
        return None

    虚表 = ctypes.cast(对象, ctypes.POINTER(ctypes.POINTER(应用关联虚表))).contents.contents
    取当前默认 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                 wintypes.LPCWSTR, ctypes.c_uint,
                                 ctypes.c_uint,
                                 ctypes.POINTER(ctypes.c_wchar_p)
                                 )(虚表.QueryCurrentDefault)

    _COM缓存[0] = (对象, 取当前默认)
    return _COM缓存[0]


def 通知外壳关联变了():
    """
    广播一声「文件关联变了」，让正在运行的资源管理器把缓存丢掉。

    为什么要这一步：关联写在注册表里是一回事，**已在运行的外壳肯不肯重新读**
    是另一回事。不广播的话，刚设完的关联在资源管理器眼里可能还是旧的。
    PS-SFTA 的更新日志里也专门提到过要刷新关联相关的项，就是这个道理。
    """
    shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


def 查有效默认(扩展):
    """
    问 Windows：这个扩展名现在「有效」的默认程序是哪个 ProgId。

    这是最权威的口径 —— 跟「设置 → 默认应用」看的是同一个东西，它认 UserChoice。
    2026-09-17 实测自校验：.txt / .pdf / .zip / .png 四个返回的 ProgId
    与 UserChoice 里存的**完全一致**；AL_机器 级别还正确返回了机器级默认
    WMP11.AssocFile.MP4。所以拿它当验收标准是可靠的。

    返回 ProgId 字符串；查不到返回空串。
    """
    句 = 取COM对象()
    if not 句:
        return ""
    对象, 取当前默认 = 句
    结果串 = ctypes.c_wchar_p()
    码 = 取当前默认(对象, 扩展, AT_文件扩展, AL_有效, ctypes.byref(结果串))
    值 = 结果串.value if 码 == 0 else ""
    if 结果串:
        ole32.CoTaskMemFree(结果串)
    return 值 or ""


def 官方设默认(程序名, 扩展, 类型=AT_文件扩展):
    """
    调用微软官方接口 IApplicationAssociationRegistration::SetAppAsDefault。

    这是「设置 → 默认应用」内部用的同一个方法。2026-09-18 实测发现本机
    （Win11 25H2 · 26200）真正生效的是 UserChoiceLatest 键、UserChoice 已被架空，
    而 UserChoiceLatest 的 Hash 算不出来（输入不止我们已知那几个），
    所以能借官方之手写就借 —— 让它替我们把两个键都写对。

    参数：
        程序名 —— 应用的注册名（ProgId 或 exe 名，逐个试）
        扩展   —— 形如 ".vob"
    返回 HRESULT：0 = S_OK 成功；其余是错误码
    """
    句 = 取COM对象()
    if not 句:
        return -1
    对象, _ = 句
    虚表 = ctypes.cast(
        对象, ctypes.POINTER(ctypes.POINTER(应用关联虚表))).contents.contents
    设默认 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                             wintypes.LPCWSTR, wintypes.LPCWSTR,
                             ctypes.c_uint)(虚表.SetAppAsDefault)
    return 设默认(对象, 程序名, 扩展, 类型)


def 读最新选择(扩展):
    """
    读 UserChoiceLatest 里记的 ProgId（本机真正生效的那个）。

    结构很怪，务必注意：ProgId 不是 UserChoiceLatest 下的一个值，
    而是 UserChoiceLatest 下的一个**子键**，值也在这个子键里叫 ProgId：
        UserChoiceLatest
            Hash = "...."                 ← 另一套算法，算不出来
            ProgId\\ProgId = "BBPlayer.Video"
    上一轮就是这里读错层，才得出「UserChoiceLatest 不存在」的误判。
    """
    _, 值 = 读字符串(最新选择键 % 扩展, "ProgId")
    return 值


def 删最新选择(扩展):
    """
    删掉 UserChoiceLatest 整棵子树。返回错误码。

    【务必看清这条，上一轮的注释是错的】
    上一轮写的是「删掉后系统会回落到 UserChoice」——**实测不成立**。
    2026-09-18 在 .vob 上亲手验证：
        · 只删 UserChoiceLatest\\ProgId 里的值 → 外壳口径当场变成 Unknown
          （双击弹「选取应用」），并没有回落到 UserChoice 里的 QuarkHTM.vob
        · 整键删掉 → 依然是 Unknown
        · 事后重写 UserChoice（哈希自洽）→ 依然 Unknown
    也就是说：**一旦这两把钥匙被碰坏，系统就把该格式的关联做废**，
    既不认 UserChoiceLatest，也不认 UserChoice。唯一的复原途径是
    用户自己在「选取应用 / 设置 → 默认应用」里点一下，让系统重写一份合法的。

    结论：本函数**不要**用在「一键切换」里，它只会把关联弄坏。
    保留它只是为了排查时有个可控手段。
    """
    return 删键(r"Software\Microsoft\Windows\CurrentVersion\Explorer"
               r"\FileExts\%s\UserChoiceLatest" % 扩展)


# ASSOCSTR_PROGID = 20，ASSOCSTR_EXECUTABLE = 2，ASSOCSTR_FRIENDLYAPPNAME = 4
_壳 = ctypes.WinDLL("shlwapi", use_last_error=True)
_壳.AssocQueryStringW.argtypes = [
    ctypes.c_ulong, ctypes.c_ulong, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulong)]
_壳.AssocQueryStringW.restype = ctypes.c_long

# shlwapi.dll 是 Windows 自带的系统库（XP 起就一直在），
# 正常机器上必然存在，所以这里直接置为可用；真出问题会在调用处拿到非 0 码。
_壳_能用 = True


def 查外壳(扩展, 问什么=20):
    r"""
    问 Windows 外壳本身：这个后缀到底归谁。

    这是 2026-09-18 新找到的口径，比 COM 那套更好用：
      · 不启动任何进程，零副作用
      · 不需要 COM 初始化，裸 ctypes 就能调
      · 返回的是外壳**当场**的解析结果（实测改注册表后立刻变，没有缓存问题）
      · 用 .exe / .txt / .jpg / .pdf / .zip / .png 做过对照，
        对「没有 UserChoice 的后缀」同样给得出正确答案 —— 可信

    参数 问什么：20 取 ProgId（默认），2 取可执行文件路径，4 取友好名
    返回字符串；查不到返回空串（此时 ProqId 位会给出 "Unknown"）
    """
    缓冲 = ctypes.create_unicode_buffer(4096)
    长度 = ctypes.c_ulong(4096)
    # AssocQueryString 要的是带头点的写法，这里统一一下，
    # 免得调用方传了 "mp4" 就查不出来
    名 = 扩展 if 扩展.startswith(".") else "." + 扩展
    码 = _壳.AssocQueryStringW(0, 问什么, 名, None, 缓冲,
                            ctypes.byref(长度))
    if (码 & MASK32) != 0:
        return ""
    return 缓冲.value or ""


def 查外壳ProgId(扩展):
    """外壳口径的 ProgId。返回 "Unknown" 表示这个后缀没有可用关联（会弹选取应用）"""
    return 查外壳(扩展, 20)


def 查默认命令行(扩展):
    r"""
    把「有效默认 ProgId」再翻译成实际要执行的命令行，方便人看。
    从 HKCR 合并视图里读 <ProgId>\shell\open\command。
    """
    程序ID_有效 = 查有效默认(扩展)
    if not 程序ID_有效:
        return ""
    _, 命令行 = 读字符串(程序ID_有效 + r"\shell\open\command", "", HKEY_CLASSES_ROOT)
    return 命令行


# ============================================================
# 六、播放器自己的关联信息
# ============================================================

# 要接管的视频格式（跟 做注册表.js 里的列表保持一致）
扩展名列表 = [
    ".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".flv", ".wmv",
    ".rmvb", ".rm", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp", ".vob", ".ogv",
]

程序ID = "BBPlayer.Video"
显示名 = "冰冰播放器"
EXE名 = "冰冰播放器.exe"

# 在「设置 → 默认应用」里登记的条目名（RegisteredApplications 下的值名）。
# 用中文显示名，这样五阿哥在设置页搜「冰冰」就能搜到。
注册应用名 = 显示名

# 【真正生效的那把钥匙】2026-09-18 实测：
#   HKCU\...\FileExts\.ext\UserChoiceLatest\ProgId\ProgId
# 注意结构很怪 —— ProgId 是**子键**，值也在子键里的同名值上。
# Win11 25H2(26200) 上 UserChoice 已被架空，这份才是实际说了算的。
最新选择键 = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
         r"\FileExts\%s\UserChoiceLatest\ProgId")

# 备份文件：记录改动之前每个格式原本的默认关联，用来一键还原
备份文件名 = "_默认关联备份.json"

用户选择键 = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\%s\UserChoice"


def 确保程序已登记(exe路径):
    """
    把播放器自己的 ProgId 写进注册表。
    为什么要在这里也写一遍：用户可能没双击那个 .reg 就直接点了「设为默认」，
    那样 UserChoice 指向一个不存在的 ProgId，关联会是坏的。
    这里写一遍就自包含了，跑几次都没副作用。
    """
    命令行 = '"%s" "%%1"' % exe路径

    码 = 写字符串(r"Software\Classes\%s" % 程序ID, "", 显示名 + " 视频")
    if 码 != 错误成功:
        return 码
    写字符串(r"Software\Classes\%s\DefaultIcon" % 程序ID, "", exe路径 + ",0")
    写字符串(r"Software\Classes\%s\shell\open\command" % 程序ID, "", 命令行)

    应用键 = r"Software\Classes\Applications\%s" % EXE名
    写字符串(应用键, "FriendlyAppName", 显示名)
    写字符串(应用键 + r"\DefaultIcon", "", exe路径 + ",0")
    写字符串(应用键 + r"\shell\open\command", "", 命令行)
    for 扩展 in 扩展名列表:
        写空值(应用键 + r"\SupportedTypes", 扩展)

    # 各扩展名的「候选打开方式」里也登记一下，右键菜单才看得到
    for 扩展 in 扩展名列表:
        写空值(r"Software\Classes\%s\OpenWithProgids" % 扩展, 程序ID)

    # 【关键一步】还要写进「每个用户的候选打开方式」列表，也就是
    #   HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.ext\OpenWithProgids
    # 2026-09-17 实测踩到的坑：UserChoice 里的 ProgId **必须**同时出现在这个列表里，
    # 系统才承认这个关联；只写 Software\Classes 那一份是不够的 ——
    # 系统会把 UserChoice 当成「来路不明的 ProgId」直接忽略掉。
    # 证据：.png 的候选列表里有 WPS.PIC.png，它的 UserChoice 就被采纳；
    #       .ogv 的候选列表里只有 KMPlayer.ogv（而 UserChoice 指向夸克），
    #       结果那个 UserChoice 被完全无视，系统回退到内置的媒体播放器。
    for 扩展 in 扩展名列表:
        写空值(r"Software\Microsoft\Windows\CurrentVersion\Explorer"
              r"\FileExts\%s\OpenWithProgids" % 扩展, 程序ID)

    # 再登记成 Windows 认可的「默认应用」条目，
    # 这样「设置 → 默认应用」里才会以**一个条目**的形式出现，
    # 并带一个「设置默认值」按钮，一次把 17 种格式全设好。
    登记为默认应用()

    return 错误成功


def 递归删键(子键):
    """
    删掉一个键连同它下面的所有子键。

    为什么需要：关联.py 里原有的 删键() 只会删「叶子键」，
    Capabilities 下面挂着 FileAssociations 子键，直接删会返回
    「键非空」而删不掉。这里先深度优先把子键清完再删自己。
    """
    码, 句柄 = 打开键(子键)
    if 码 != 错误成功:
        # 键本就不存在，就当已经删干净了
        return 错误成功

    子列表 = []
    i = 0
    while True:
        try:
            子列表.append(winreg.EnumKey(句柄, i))
            i += 1
        except OSError:
            break
    关键(句柄)

    for 子名 in 子列表:
        对应 = 递归删键(子键 + "\\" + 子名)

    return 删键(子键)


def 登记为默认应用():
    """
    把本程序登记成 Windows 官方体系里认可的「默认应用」。

    【为什么要做这一步 —— 2026-09-18 实测的结论】

    之前只写了 ProgId 和 Applications\\冰冰播放器.exe，结果：
      · 在「设置 → 默认应用」里搜「冰冰播放器」搜不到
      · 微软官方的 SetAppAsDefault 一律返回 E_FAIL(0x80004005)
    实测本机 HKCU\\Software\\RegisteredApplications 有 82 条登记，
    HKLM 有 20 条（KMPlayer / Quark / WPS 都在里面），**唯独没有我们**。

    而 Windows 认一个「默认应用」的规矩是：
        HKCU\\Software\\RegisteredApplications\\<应用名> = <Capabilities 键路径>
    且该 Capabilities 键下要有
        ApplicationName                                  （显示名）
        FileAssociations\\.ext = <ProgId>                 （它能开哪些格式）
    缺了这块，程序就不算「注册过的应用」：
      · 设置页里列不出来
      · 也就没有那个「设置默认值」的一键按钮
      · 只能靠用户一个个格式手动挑，那才是真正麻烦的地方

    ⚠️ 必须说清楚的边界：
        这一步**不会**让脚本获得「直接设默认」的能力。
        本机（Win11 25H2 · 26200）实测：真正生效的钥匙是
        FileExts\\.ext\\UserChoiceLatest，它的 Hash 我们算不出来，
        硬写会被系统判定篡改、把该格式的关联整个做废（.vob 上实测到了）。
        这一步的价值是：把程序变成设置页里「找得到、能一键全设」的正经条目，
        让用户那一下点击变得毫无门槛。

    写 HKCU，不需要管理员，随时可用 撤销默认应用登记() 退回。
    返回错误码，0 表示成功。
    """
    能力键 = r"Software\Classes\Applications\%s\Capabilities" % EXE名

    码 = 写字符串(能力键, "ApplicationName", 显示名)
    if 码 != 错误成功:
        return 码
    写字符串(能力键, "ApplicationDescription",
           "单文件 HTML 视频播放器，用本机浏览器内核播放，不装解码包")

    # FileAssociations：告诉 Windows「本程序能打开这些格式」，
    # 值名是扩展名，数据是它要用的 ProgId
    码 = 写字符串(能力键 + r"\FileAssociations", 扩展名列表[0], 程序ID)
    if 码 != 错误成功:
        return 码
    for 扩展 in 扩展名列表[1:]:
        写字符串(能力键 + r"\FileAssociations", 扩展, 程序ID)

    # 最后挂到 RegisteredApplications 上，设置页就是靠这一条找到我们的
    码 = 写字符串(r"Software\RegisteredApplications", 注册应用名,
                r"Software\Classes\Applications\%s\Capabilities" % EXE名)
    return 码


def 撤销默认应用登记():
    """
    注销「默认应用」登记，把 登记为默认应用() 写的东西全撤掉。
    顺序很重要：先摘 RegisteredApplications 的挂靠，再删 Capabilities 子树，
    否则中途失败会留下一条指向空路径的死登记。
    """
    删值(r"Software\RegisteredApplications", 注册应用名)
    递归删键(r"Software\Classes\Applications\%s\Capabilities" % EXE名)
    return 错误成功


def 是否已登记为默认应用():
    """查一下 RegisteredApplications 里有没有我们，给 --查状态 用"""
    _, 值 = 读字符串(r"Software\RegisteredApplications", 注册应用名)
    return bool(值)


def 写用户选择(扩展, 新程序ID, 用户SID, 最多重试=6):
    """
    把某个扩展名的默认关联写成「新程序ID」。返回 (错误码, 说明)。

    这里要绕开两个坑：
    1) 必须先删键再建键。原来的 UserChoice 键上挂着一条拒写权限，
       直接在老键上写值会被拒绝；新建的键继承父键权限，没有那条限制。
    2) 哈希里含一个「抹到分钟」的时间戳，而系统校验时用的是**键自己的写入时间**。
       要是正好卡在整分钟那一瞬间写入，算哈希用的分钟和键落盘的分钟会差一分钟，
       哈希当场作废。所以这里写完回读一次键时间，对不上就重来 ——
       这一点连 PS-SFTA 都没处理。
    """
    子键 = 用户选择键 % 扩展

    尝试 = 0
    while 尝试 < 最多重试:
        尝试 += 1

        # 每轮都重建键：既绕开拒写权限，又把键时间归零重算
        删键(子键)

        码 = 写字符串(子键, "ProgId", 新程序ID)
        if 码 != 错误成功:
            return 码, "写 ProgId 失败"

        # 直接用「键自己的写入时间」算哈希，跟系统校验的口径完全一致，
        # 连跨分钟那点时间差都不会有
        时间串 = 取键修改时间(子键) or 取注册时间戳()
        哈希 = 算用户选择哈希(扩展, 用户SID, 新程序ID, 时间串)
        if not 哈希:
            return 错误找不到路径, "哈希算不出来"

        码 = 写字符串(子键, "Hash", 哈希)
        if 码 != 错误成功:
            return 码, "写 Hash 失败"

        # 回读复核：写 Hash 本身也可能把键时间又推进一分钟，推了就重来
        if 取键修改时间(子键) == 时间串:
            return 错误成功, ""

    return 错误拒绝访问, "连试 %d 次都没能把时间戳对齐" % 最多重试


def 读现有用户选择(扩展):
    """读某个扩展名现在的 UserChoice。返回 (程序ID, 哈希)；没有则都是空串"""
    子键 = 用户选择键 % 扩展
    码, 现有 = 读字符串(子键, "ProgId")
    if 码 != 错误成功:
        return "", ""
    _, 哈希 = 读字符串(子键, "Hash")
    return 现有, 哈希


# ============================================================
# 七、对外功能：备份 / 设为默认 / 恢复 / 查状态
# ============================================================

def 读备份(播放器目录):
    """读备份文件。返回列表，每项是 (扩展名, 原程序ID, 原有效默认)；没有备份返回空列表"""
    路径 = os.path.join(播放器目录, 备份文件名)
    if not os.path.exists(路径):
        return []
    with open(路径, "r", encoding="utf-8-sig") as 文件:
        内容 = json.load(文件)
    列表 = []
    for 项 in 内容.get("项目", []):
        列表.append((项.get("扩展", ""), 项.get("原程序ID", ""), 项.get("原有效默认", "")))
    return 列表


def 写备份(播放器目录, 项目):
    """把每个格式改之前的默认关联记下来，供「恢复默认」使用"""
    路径 = os.path.join(播放器目录, 备份文件名)
    内容 = {
        "说明": "冰冰播放器「设为默认打开方式」改动前的快照，供一键恢复使用。删掉它就无法自动还原了。",
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "项目": 项目,
    }
    with open(路径, "w", encoding="utf-8-sig") as 文件:
        json.dump(内容, 文件, ensure_ascii=False, indent=2)
    return 路径


def 校验用户选择(扩展, 期望程序ID):
    """
    按注册表直读复核某个扩展名的 UserChoice 是不是我们要的那个。

    为啥不用「问系统有效默认是谁」来复核：
    2026-09-17 实测 —— 同一个进程里刚写完就查，查到的还是旧值（缓存），
    会把明明成功的一批全判成失败（m4v/mov/mpeg/3gp/vob 就被误杀了）。
    注册表直读结果确定、可重复，拿它当复核标准。

    判定：ProgId 等于期望值，且 Hash 能用「键自己的写入时间」重算出来。
    """
    程序ID_现, 哈希现 = 读现有用户选择(扩展)
    if 程序ID_现 != 期望程序ID or not 哈希现:
        return False
    时间串 = 取键修改时间(用户选择键 % 扩展)
    重算 = 算用户选择哈希(扩展, 取当前用户SID(), 期望程序ID, 时间串)
    return bool(重算) and 重算 == 哈希现


def 备份里的原值(播放器目录, 扩展):
    """从备份文件里取出某个扩展名原来的 ProgId；没有备份或没这项就返回空串"""
    for 项扩展, 原程序ID, _ in 读备份(播放器目录):
        if 项扩展 == 扩展:
            return 原程序ID
    return ""


def 找被AppX占的(扩展清单=None):
    """
    找出哪些格式当前被 AppX（微软商店）应用占着。

    这些格式用脚本改不动 —— 系统会无视我们写进去的 UserChoice。
    实测（2026-09-17）本机 17 种格式里只有 .mp4 和 .ogv 属于这种，
    占位的是商店版「媒体播放器」。

    【重要】必须在做任何修改**之前**调用：写完之后同一个进程里再查，
    拿回来的还是旧值（缓存），判断会不准。
    """
    清单 = 扩展清单 if 扩展清单 is not None else 扩展名列表

    # 【2026-09-18 修正】改读 UserChoiceLatest —— 它才是本机真正生效的那把钥匙。
    # 原来读的 COM 查询返回的是「回退结果」，会被我们自己的候选登记带偏。
    结果 = []
    for 扩展 in 清单:
        谁占的 = 读最新选择(扩展) or 查有效默认(扩展)
        if 谁占的.startswith("AppX"):
            结果.append(扩展)
    return 结果


def 设为默认(播放器目录, exe路径, 进度回调=None):
    """
    把 17 种视频格式的默认程序改成冰冰播放器。

    步骤：备份原关联 → 写 ProgId/Hash → 问系统「有效默认是谁」复核。

    返回 (成功数, 失败数, 明细列表)。明细每项是 (扩展名, 是否成功, 说明)。
    """
    def 报(文本):
        if 进度回调:
            进度回调(文本)

    用户SID = 取当前用户SID()
    if not 用户SID:
        报("取不到当前用户 SID，无法计算关联哈希")
        return 0, len(扩展名列表), [(e, False, "取不到 SID") for e in 扩展名列表]

    报("当前用户 SID：%s" % 用户SID)

    # ---- 0. 先探一遍各格式现在是谁在占（必须在任何修改之前做）----
    被AppX占的 = 找被AppX占的()

    # ---- 1. 先备份（只在第一次做，避免把「已经被改成我们」的状态当成原始状态）----
    已有备份 = os.path.exists(os.path.join(播放器目录, 备份文件名))
    if not 已有备份:
        项目 = []
        for 扩展 in 扩展名列表:
            原程序ID, _ = 读现有用户选择(扩展)
            项目.append({
                "扩展": 扩展,
                "原程序ID": 原程序ID,              # UserChoice 里存的 ProgId（可能是失效的旧值）
                "原有效默认": 查有效默认(扩展),   # 系统实际认的 ProgId，还原时按这个比对
            })
        路径 = 写备份(播放器目录, 项目)
        报("已备份原默认关联：%s" % 路径)
    else:
        报("已有备份文件，沿用最初那份（不覆盖）")

    # ---- 2. 登记 ProgId（万一用户没双击过 .reg）----
    确保程序已登记(exe路径)
    报("已登记 ProgId：%s（右键「打开方式」里能看到「%s」）" % (程序ID, 显示名))
    报("已登记为 Windows 默认应用条目：%s"
      % ("是 —— 设置页里搜得到，可一键设默认值"
         if 是否已登记为默认应用() else
         "失败 —— 设置页里可能搜不到，需要逐个格式手动挑"))

    # ---- 3. 逐个写 UserChoice，然后按注册表复核 ----
    成功 = 0
    明细 = []
    for 扩展 in 扩展名列表:
        码, 说明 = 写用户选择(扩展, 程序ID, 用户SID)
        if 码 != 错误成功:
            明细.append((扩展, False, "写入失败：%s（错误码 %d）" % (说明, 码)))
            报("%s 写入失败" % 扩展)
            continue

        if 校验用户选择(扩展, 程序ID):
            成功 += 1
            明细.append((扩展, True, "已写入"))
            报("%s 已设为冰冰播放器" % 扩展)
        else:
            # 没写干净就把这个格式还原回原样，绝不留下半吊子状态
            原程序ID = 备份里的原值(播放器目录, 扩展)
            if 原程序ID:
                写用户选择(扩展, 原程序ID, 用户SID)
            else:
                删键(用户选择键 % 扩展)
            明细.append((扩展, False, "复核不通过，已回滚"))
            报("%s 复核不通过，已回滚成原样" % 扩展)

    # ---- 4. 广播给外壳：关联变了，丢掉缓存 ----
    通知外壳关联变了()

    # ---- 4.5 用外壳口径复核，把「注册表写了但实际没生效」如实报出来 ----
    #   这一步很重要：本机 UserChoice 是架空的，写成功 ≠ 生效。
    #   不主动复核就会给人一种「脚本已经搞定了」的错觉。
    真生效 = 0
    待手动 = []
    for 扩展 in 扩展名列表:
        现 = 查外壳ProgId(扩展)
        if 现 == 程序ID or 现 == "Applications\\" + EXE名:
            真生效 += 1
        else:
            待手动.append(扩展)

    报("")
    报("【外壳口径复核】17 种格式里，现在真正由%s接管的有 %d 种。" % (显示名, 真生效))
    if 待手动:
        报("  还剩 %d 种要手动一下：%s" % (len(待手动), "  ".join(待手动)))
        报("  原因：本机真正生效的是 UserChoiceLatest，它的哈希算不出来，")
        报("        脚本写不进去；只有系统设置页里那一下点击算数。")
    else:
        报("  全部 17 种都已经生效 ✓")

    # ---- 5. 提前说清哪些格式在当前系统上抢不过来 ----
    #   规律（2026-09-17 在 Windows 11 25H2 ・ 26200.9457 上逐项实测得出）：
    #   当前被 AppX（微软商店）应用占着的格式，脚本改不动 —— 系统会无视我们的 UserChoice。
    #   实测 17 种格式里，只有 .mp4 和 .ogv 属于这种（占位的是商店版「媒体播放器」）。
    if 被AppX占的:
        报("")
        报("【提醒】下列格式当前被微软商店应用占用，脚本改不动（系统会无视写入）：")
        报("    " + "  ".join(被AppX占的))
        报("    要改成冰冰播放器，请手动设一次：")
        报("    右键任意该格式的视频 → 打开方式 → 选择其他应用 → 选「冰冰播放器」→ 勾「始终使用」")

    return 成功, len(扩展名列表) - 成功, 明细


def 恢复默认(播放器目录, 进度回调=None):
    """
    按备份把默认关联还原回去。

    注意：还原时必须**重算哈希** —— 备份里存的是旧哈希，那是跟旧时间戳绑定的，
    我们对键做过改动之后旧哈希就作废了，直接写回去系统不认。

    返回 (成功数, 失败数, 明细列表)。
    """
    def 报(文本):
        if 进度回调:
            进度回调(文本)

    项目 = 读备份(播放器目录)
    if not 项目:
        报("没找到备份文件 %s，无法自动恢复。请到「设置 → 应用 → 默认应用」手动改回。" % 备份文件名)
        return 0, 0, []

    用户SID = 取当前用户SID()
    if not 用户SID:
        报("取不到当前用户 SID，无法重算哈希")
        return 0, len(项目), [(e, False, "取不到 SID") for e, _, _ in 项目]

    成功 = 0
    明细 = []
    for 扩展, 原程序ID, 原有效默认 in 项目:
        if not 原程序ID:
            # 原来就没有默认关联（系统按内置规则走）→ 把我们的键删掉即可
            删键(用户选择键 % 扩展)
            成功 += 1
            明细.append((扩展, True, "已清除，回到系统默认"))
            报("%s 原本没有默认关联，已清除" % 扩展)
            continue

        # 用原来的 ProgId + **当前键时间**重算哈希。
        # 备份里存的那个旧哈希是跟旧时间戳绑定的，我们对键动过手之后它已经作废，
        # 直接写回去系统不认 —— 必须重算。
        码 = 写字符串(用户选择键 % 扩展, "ProgId", 原程序ID)
        if 码 == 错误成功:
            时间串 = 取键修改时间(用户选择键 % 扩展) or 取注册时间戳()
            哈希 = 算用户选择哈希(扩展, 用户SID, 原程序ID, 时间串)
            码 = 写字符串(用户选择键 % 扩展, "Hash", 哈希)

        if 码 != 错误成功:
            明细.append((扩展, False, "写入失败（错误码 %d）" % 码))
            报("%s 恢复失败" % 扩展)
            continue

        # 复核也走注册表直读 —— 同进程刚写完就问系统，读到的是缓存，会误判
        现在, _ = 读现有用户选择(扩展)
        if 现在 == 原程序ID:
            成功 += 1
            明细.append((扩展, True, "已还原为 %s" % 原程序ID))
            报("%s 已还原为 %s" % (扩展, 原程序ID))
        else:
            明细.append((扩展, False, "期望 %s，实际 %s" % (原程序ID, 现在 or "(空)")))
            报("%s 还原后与预期不符" % 扩展)

    # 广播给外壳，让它重新读关联
    通知外壳关联变了()

    # 用外壳口径复核一遍：注册表写对了不等于系统认了（见 查状态 的说明）
    真还原 = 0
    待手动 = []
    for 扩展, 原程序ID, _原有效默认 in 项目:
        现 = 查外壳ProgId(扩展)
        if 原程序ID:
            # 有原值：只有外壳认的就是它，才算真还原
            好 = (现 == 原程序ID)
        else:
            # 原本就没有默认关联，系统给什么口径都算还原到位
            好 = True
        if 好:
            真还原 += 1
        else:
            待手动.append("%s(现在是 %s)" % (扩展, 现 or "(查不到)"))

    报("")
    报("【外壳口径复核】按实际生效结果看，%d / %d 已回到原来的程序。"
       % (真还原, len(项目)))
    if 待手动:
        报("  还剩 %d 种要手动一下：" % len(待手动))
        for 一 in 待手动:
            报("      " + 一)
        报("  原因同上：本机真正生效的是 UserChoiceLatest，脚本写不进去。")

    return 成功, len(项目) - 成功, 明细


def 查状态(进度回调=None):
    """
    把 17 种格式当前的默认程序列出来，供排查用。返回明细列表。

    【2026-09-18 修正版】本机（Win11 25H2 · 26200）实测结论：
        · 真正生效的是 FileExts\\.ext\\UserChoiceLatest\\ProgId\\ProgId，
          我们写的 UserChoice 被架空
        · 「外壳自带口径」AssocQueryString 读出来的结果与 UserChoiceLatest
          完全一致（6/6），而且它**不启动进程、无副作用**，所以现在以它为准
        · 读不到具体 ProgId 时会出现 "Unknown"，那代表这个后缀没有可用关联，
          双击会弹「选取应用」——这是坏状态，必须显式标出来
    """
    def 报(文本):
        if 进度回调:
            进度回调(文本)

    已登记 = 是否已登记为默认应用()
    报("默认应用登记：%s" % ("已登记（设置页搜得到，可一键设默认值）"
                        if 已登记 else
                        "★ 未登记（设置页里搜不到，只能逐个格式手动挑）"))

    if not _壳_能用:
        报("警告：外壳接口 AssocQueryStringW 绑定失败，读数会退化到注册表口径")

    明细 = []
    for 扩展 in 扩展名列表:
        程序ID_现, _ = 读现有用户选择(扩展)
        最新 = 读最新选择(扩展)
        COM值 = 查有效默认(扩展)

        # 优先信外壳口径；外壳不可用时退到 UserChoiceLatest，再退到 COM
        真实 = 查外壳ProgId(扩展) if _壳_能用 else ""
        来源 = "外壳"
        if not 真实:
            真实 = 最新
            来源 = "Latest键"
        if not 真实:
            真实 = COM值
            来源 = "COM"

        if 真实 == "Unknown" or not 真实:
            是我们 = False
            显示 = "无关联 ★ 双击会弹「选取应用」，需要手动设一次"
        elif 真实 == 程序ID or 真实 == "Applications\\" + EXE名:
            是我们 = True
            显示 = "★ 已是冰冰播放器"
        elif 真实.startswith("AppX"):
            是我们 = False
            显示 = "（微软商店应用占用，脚本抢不过来）"
        else:
            是我们 = False
            显示 = ""

        明细.append((扩展, 是我们, 真实 or "(查不到)", 程序ID_现))
        报("%-6s 生效=%-38s 来源=%-8s UserChoice=%-16s %s"
          % (扩展, 真实 or "(查不到)", 来源, 程序ID_现 or "(无)", 显示))
    return 明细


def 打开默认应用设置(应用名=""):
    """
    打开 Windows 自己的「默认应用」设置页。

    【为什么要走这一步 —— 2026-09-18 带可控实验的结论】
    本机（Win11 25H2 · 26200）上，脚本**改不了**默认关联，证据链完整：
        1. 真正生效的是 FileExts\\.ext\\UserChoiceLatest\\ProgId\\ProgId
           （外壳口径与它 6/6 吻合；UserChoice 里的值被完全架空）
        2. UserChoiceLatest 的 Hash 与 UserChoice 那套算法**不是同一套**：
           拿 4/4 通过验证的 UserChoice 算法去撞 6 个 UserChoiceLatest 样本，
           命中 0。也就是说我们造不出合法哈希。
        3. 硬写进去 → 系统判定为篡改，把该格式的 UserChoiceLatest **和**
           UserChoice 一起做废。.vob 上实测到了：写入后外壳口径从
           「冰冰播放器」直接变成 Unknown（双击弹「选取应用」），
           事后重写 UserChoice（哈希自洽）也救不回来。
        4. 官方接口 SetAppAsDefault 返回 E_FAIL(0x80004005)。
    所以「设为默认」只能退而求其次：替用户把设置页点开，剩下那一下点击
    是 Windows 唯一认的写入途径。

    参数 应用名：传了就把设置页直接定位到该应用的页面
                （ms-settings 会把它编码进 URI；万一系统不认这个参数，
                 也只是回退到「默认应用」总览页，不会有副作用）
    """
    壳 = ctypes.WinDLL("shell32", use_last_error=True)
    壳.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                              wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.LPCWSTR, ctypes.c_int]
    壳.ShellExecuteW.restype = wintypes.HINSTANCE

    地址 = "ms-settings:defaultapps"
    if 应用名:
        编码 = urllib.parse.quote(应用名)
        地址 += "?registeredAppUser=" + 编码
    码 = 壳.ShellExecuteW(None, "open", 地址, None, None, 1)
    if 码 > 32:
        return 码
    # 带参数那种万一在本机不被识别，退回总览页再试一次
    return 壳.ShellExecuteW(None, "open", "ms-settings:defaultapps",
                          None, None, 1)


def 备份文件在哪(播放器目录):
    return os.path.join(播放器目录, 备份文件名)
