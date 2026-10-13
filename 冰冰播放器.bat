@echo off
setlocal

rem ============================================================
rem  冰冰播放器 · 桌面启动器（路径写死版）
rem
rem  本文件适合放在桌面 / 任务栏 / 开始菜单，双击即开播放器。
rem  与项目内「启动冰冰播放器.bat」的区别：
rem    项目内那个用 %~dp0 取路径，必须留在项目目录里；
rem    这个是路径写死的，可以放到任何位置。
rem  所以项目目录一旦移动，请同步改下面的 PLAYER / PAGEDIR 变量。
rem
rem  双击后会发生什么：
rem    · 直接双击（没拖东西）→ 播放器以空状态打开，不带出上次的列表
rem    · 拖了文件 / 文件夹到本图标上 → 扫描那个目录并列出里面的视频
rem
rem  【不留痕】本播放器刻意不记任何东西：
rem    · 不记播放列表 —— 每次打开都是现扫的，上次那份会被清掉
rem    · 不记音量、不记播放列表面板的展开状态
rem    · 不自动播放上次的视频
rem    · 浏览器以无痕模式启动，不在 Chrome 里留下 file:// 浏览历史
rem
rem  【编码说明】本文件必须是 GBK / ANSI 编码 + CRLF 换行。
rem  若另存为 UTF-8 或改成 LF 换行，cmd 会因多字节解码错乱
rem  而吞掉行首字符，中文路径也会乱码。
rem  中文 Windows 的 cmd 默认代码页就是 936，这里不需要也不应该加 chcp。
rem
rem  用系统已有的 Chrome / Edge 以「应用模式 + 无痕」打开播放器：
rem    · 没有地址栏、没有标签页，外观就是一个独立播放器
rem    · 复用系统浏览器内核，不额外打包一份 Chromium
rem    · 无痕的代价：不能复用已在运行的 Chrome 进程，会另起一个实例，
rem      内存比「复用进程」时多一点。这是「不留痕」必须付的成本。
rem ============================================================

rem ---- 播放器主程序位置（写死，项目移动后改这里）----
set "PLAYER=D:\你的路径\冰冰播放器\冰冰播放器.html"
set "PAGEDIR=D:\你的路径\冰冰播放器"

rem ---- 固定片库目录（可选）----
rem 不设就留空：双击本文件时不会扫描任何目录，播放器以空状态打开。
rem 想固定扫某个片库就填进去，例如：set "LIBDIR=D:\片库"
rem 拖文件 / 文件夹到本文件图标上时，优先用被拖进来的路径。
set "LIBDIR="

if not exist "%PLAYER%" (
    echo.
    echo [错误] 找不到播放器主程序：
    echo        %PLAYER%
    echo.
    echo 可能原因：项目目录被移动或重命名了。
    echo 解决办法：右键本文件 - 编辑，把上面的路径改成实际位置。
    echo.
    pause
    exit /b 1
)

rem ---- 生成播放列表 _播放列表.js ----
rem 扫描目标优先级：
rem   1) 拖到本文件图标上的 文件 / 文件夹（%1）
rem   2) 上面设定的固定片库 LIBDIR
rem   3) 都没有时：_扫描.ps1 会写一份空清单，把上次的列表清掉
rem 扫描交给独立的 ps1：bat 里嵌套引号加中文路径的转义几乎没法维护。
if not exist "%PAGEDIR%\_扫描.ps1" goto NO_SCAN

set "SCANTARGET=%~1"
if "%SCANTARGET%"=="" set "SCANTARGET=%LIBDIR%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PAGEDIR%\_扫描.ps1" -Target "%SCANTARGET%" -PlayerDir "%PAGEDIR%"
goto SCAN_DONE

:NO_SCAN
echo [提示] 未找到 _扫描.ps1，本次跳过播放列表处理。

:SCAN_DONE

rem ---- 按优先级查找浏览器 ----
set "BROWSER="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe"                          set "BROWSER=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "BROWSER=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"     set "BROWSER=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" set "BROWSER=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe"  set "BROWSER=C:\Program Files\Microsoft\Edge\Application\msedge.exe"

rem ---- 找不到浏览器就交给系统默认程序 ----
if not defined BROWSER (
    echo [提示] 没有找到 Chrome 或 Edge，改用系统默认浏览器打开。
    start "" "%PLAYER%"
    exit /b 0
)

rem ---- 反斜杠换成正斜杠，拼成 file:/// 地址 ----
set "URLPATH=%PLAYER:\=/%"

rem 启动参数说明：
rem   --incognito                          无痕启动，不在 Chrome 里留浏览历史
rem   --app=...                            以应用模式打开（无地址栏 / 标签页）
rem   --autoplay-policy=no-user-gesture-required  允许自动开始播放
rem   --allow-file-access-from-files       允许 file:// 页面读取本地文件。
rem     不加这个参数时，往窗口里拖文件夹会读不出来
rem     （2026-09-17 实测：entry.file() 会报 EncodingError）。
start "" "%BROWSER%" --incognito --app="file:///%URLPATH%" --window-size=1280,720 --autoplay-policy=no-user-gesture-required --allow-file-access-from-files

exit /b 0