@echo off
setlocal

rem ============================================================
rem  冰冰播放器 · 查看当前默认打开方式
rem
rem  双击本文件会弹一个窗口，列出 17 种视频格式
rem  「双击之后实际会用谁打开」。
rem
rem  这个数不是读注册表读出来的，而是直接问 Windows 外壳本身
rem  （AssocQueryString）—— 跟双击文件时走的是同一套判断，
rem  而且不会启动任何程序，看一眼没有副作用。
rem
rem  标 ★ 的就是当前由冰冰播放器接管。
rem  如果某个格式显示「无关联」，双击它会弹「选取应用」，
rem  随便选一次程序并勾「始终」，系统就会重写一份合法关联，即可修好。
rem
rem  排查问题时也看 冰冰播放器壳.log，里面每一步都有记录。
rem
rem  【编码说明】本文件必须是 GBK / ANSI 编码 + CRLF 换行。
rem    若另存为 UTF-8 或改成 LF 换行，cmd 会因多字节解码错乱
rem    而吞掉行首字符，中文也会乱码。
rem    中文 Windows 的 cmd 默认代码页就是 936，不需要加 chcp。
rem ============================================================

cd /d "%~dp0"

set "EXE=%~dp0冰冰播放器.exe"

if not exist "%EXE%" (
    echo.
    echo [错误] 找不到主程序：
    echo        %EXE%
    echo.
    echo 可能原因：项目目录被移动或重命名了。
    echo 解决办法：把本文件放回 冰冰播放器.exe 所在目录再双击。
    echo.
    pause
    exit /b 1
)

echo 正在查询各格式当前实际生效的默认程序...
echo

start "" "%EXE%" --查状态

exit /b 0
