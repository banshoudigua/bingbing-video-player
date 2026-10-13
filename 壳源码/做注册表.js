// 生成「加入打开方式」与「移出打开方式」两个 .reg 文件
//
// 为什么用 Node 而不是直接写文件：
//   .reg 里含中文，必须存成 **UTF-16LE + BOM**，Windows 才认（否则"打开方式"里显示乱码）。
//   Write 工具只能写 UTF-8，所以这里用 Node 精确控制字节。
//
// 只动 HKCU（当前用户），不碰 HKLM —— 所以不需要管理员权限，也随时可退。

const fs = require('fs');
const path = require('path');

// 播放器目录 = 本脚本所在目录的上一层。
// 脚本放在项目里的「壳源码/」下，所以 .. 正好是播放器根目录（冰冰播放器.exe 在那儿）。
// 这样脚本跟着项目走，挪到哪都不用改。
const 播放器目录 = path.resolve(__dirname, '..');
const EXE = 播放器目录 + '\\冰冰播放器.exe';
const EXE名 = '冰冰播放器.exe';
const PROGID = 'BBPlayer.Video';
const 显示名 = '冰冰播放器';

// 常见音视频格式
//   视频 —— 最初选定的范围
//   音频 —— 2026-10-13 追加（需求：增加常见音频文件的播放支持）
//
// 【ProgId 故意保持 BBPlayer.Video 不变】
//   改名会让已经登记好的那 17 种视频格式关联全部失效（登记散落在
//   RegisteredApplications / Capabilities / 各扩展名的 OpenWithProgids 里）。
//   ProgId 只是个内部标识，用户在「打开方式」里看到的名字来自
//   Capabilities\ApplicationName，所以叫 Video 却含音频并不会露馅。
const 扩展名 = [
  // ---- 视频 ----
  '.mp4', '.m4v', '.mov', '.webm', '.mkv', '.avi', '.flv', '.wmv',
  '.rmvb', '.rm', '.ts', '.m2ts', '.mpg', '.mpeg', '.3gp', '.vob', '.ogv',
  // ---- 音频 ----
  '.mp3', '.m4a', '.m4b', '.aac', '.wav', '.flac', '.ogg', '.oga',
  '.opus', '.wma', '.ape', '.aiff', '.amr', '.mka', '.mid'
];

// .reg 里反斜杠和引号都要转义
function 转义(s) { return s.replace(/\\/g, '\\\\').replace(/"/g, '\\"'); }

const 命令行值 = '"' + 转义(EXE) + ' \\"%1\\""';

// ---------------- 注册 ----------------
const 注册 = [];
注册.push('Windows Registry Editor Version 5.00');
注册.push('');
注册.push('; ============================================================');
注册.push(';  冰冰播放器 · 加入「打开方式」列表');
注册.push(';');
注册.push(';  只写 HKEY_CURRENT_USER，不需要管理员权限。');
注册.push(';  它**不会**抢走你现在的默认播放器 —— 只是让右键菜单的');
注册.push(';  「打开方式 → 选择其他应用」里多出一个「冰冰播放器」。');
注册.push(';  想让它当默认，自己在那个对话框里勾「始终使用」即可。');
注册.push(';');
注册.push(';  想撤销：双击同目录下的「卸载-移出打开方式.reg」。');
注册.push('; ============================================================');
注册.push('');
注册.push('; ---- 主程序路径（项目搬走要改这里，改完重新双击本文件）----');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\' + PROGID + ']');
注册.push('@="' + 显示名 + ' 视频"');
注册.push('');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\' + PROGID + '\\DefaultIcon]');
注册.push('@="' + 转义(EXE) + ',0"');
注册.push('');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\' + PROGID + '\\shell\\open\\command]');
注册.push('@=' + 命令行值);
注册.push('');
注册.push('; ---- 让程序本身出现在「打开方式」的程序列表里 ----');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + ']');
注册.push('"FriendlyAppName"="' + 显示名 + '"');
注册.push('');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + '\\DefaultIcon]');
注册.push('@="' + 转义(EXE) + ',0"');
注册.push('');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + '\\shell\\open\\command]');
注册.push('@=' + 命令行值);
注册.push('');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + '\\SupportedTypes]');
// SupportedTypes 下面的值必须是「空字符串」，用变量拼避免引号数错
const 空串值 = '""';
扩展名.forEach(function (e) { 注册.push('"' + e + '"=' + 空串值); });
注册.push('');
注册.push('; ---- 登记成 Windows 认可的「默认应用」条目 ----');
注册.push(';      为什么要这一块（2026-09-18 实测）：');
注册.push(';        本机 HKCU\\Software\\RegisteredApplications 有 82 条登记、HKLM 有 20 条');
注册.push(';        （KMPlayer / Quark / WPS 都在），原先唯独没有冰冰播放器。');
注册.push(';        缺了这块，程序在「设置 → 默认应用」里搜不到，');
注册.push(';        也就没有那个「设置默认值」按钮，只能逐个格式手动挑。');
注册.push(';      补上之后，设置页里点一次「设置默认值」即可 ' + 扩展名.length + ' 种格式全设。');
注册.push(';      注意：它只是让程序「被系统当成一个正经应用」；');
注册.push(';            Windows 11 25H2 真正生效的默认关联钥匙带校验值，');
注册.push(';            脚本仍然写不进去，最终那一下点击必须由人来完成。');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + '\\Capabilities]');
注册.push('"ApplicationName"="' + 显示名 + '"');
注册.push('"ApplicationDescription"="单文件 HTML 视频播放器，用本机浏览器内核播放，不装解码包"');
注册.push('');
注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + '\\Capabilities\\FileAssociations]');
// 值名是扩展名，数据是它要用的 ProgId
扩展名.forEach(function (e) { 注册.push('"' + e + '"="' + PROGID + '"'); });
注册.push('');
注册.push('; ---- 挂到 RegisteredApplications 上，设置页靠这一条找到我们 ----');
注册.push('[HKEY_CURRENT_USER\\Software\\RegisteredApplications]');
注册.push('"' + 显示名 + '"="Software\\\\Classes\\\\Applications\\\\' + EXE名 + '\\\\Capabilities"');
注册.push('');
注册.push('; ---- 各媒体格式的「候选打开方式」里加上本程序 ----');
注册.push(';      注意：只加 OpenWithProgids，不设默认值，所以不会被抢成默认打开方式');
扩展名.forEach(function (e) {
  注册.push('[HKEY_CURRENT_USER\\Software\\Classes\\' + e + '\\OpenWithProgids]');
  注册.push('"' + PROGID + '"=hex(0):');      // REG_NONE，规范写法
  注册.push('');
});

// ---------------- 卸载 ----------------
const 卸载 = [];
卸载.push('Windows Registry Editor Version 5.00');
卸载.push('');
卸载.push('; ============================================================');
卸载.push(';  冰冰播放器 · 移出「打开方式」列表');
卸载.push(';');
卸载.push(';  只删掉本播放器自己写进去的东西，你原本的默认播放器不受影响。');
卸载.push('; ============================================================');
卸载.push('');
卸载.push('[-HKEY_CURRENT_USER\\Software\\Classes\\' + PROGID + ']');
卸载.push('');
卸载.push('[-HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + ']');
卸载.push('');
卸载.push('; ---- 注销「默认应用」登记（让设置页里不再出现在这个程序）----');
卸载.push(';      顺序讲究：先摘掉 RegisteredApplications 的挂靠，再删 Capabilities，');
卸载.push(';      反过来的话，中间出错会留下一条指向空路径的死登记。');
卸载.push('[HKEY_CURRENT_USER\\Software\\RegisteredApplications]');
卸载.push('"' + 显示名 + '"=-');
卸载.push('');
卸载.push('[-HKEY_CURRENT_USER\\Software\\Classes\\Applications\\' + EXE名 + '\\Capabilities]');
卸载.push('');
卸载.push('; ---- 把这些格式下我们加的那个候选打开方式删掉 ----');
扩展名.forEach(function (e) {
  卸载.push('[HKEY_CURRENT_USER\\Software\\Classes\\' + e + '\\OpenWithProgids]');
  卸载.push('"' + PROGID + '"=-');
  卸载.push('');
});

// 写 UTF-16LE + BOM —— 只有这样 Windows 的 regedit 才认中文
function 写注册表文件(路径, 行) {
  const 文本 = '\uFEFF' + 行.join('\r\n') + '\r\n';
  fs.writeFileSync(路径, Buffer.from(文本, 'utf16le'));
  const b = fs.readFileSync(路径);
  console.log(路径 + '  字节=' + b.length + '  BOM=' + (b[0] === 0xFF && b[1] === 0xFE ? 'FFFE ✓' : '无 ✗'));
}

写注册表文件(播放器目录 + '\\注册-加入打开方式.reg', 注册);
写注册表文件(播放器目录 + '\\卸载-移出打开方式.reg', 卸载);
console.log('\n共关联 ' + 扩展名.length + ' 种格式：' + 扩展名.join(' '));
