# 撮影の道具が起動した処理（ヘッドレスの Chrome、shoot.mjs などの node、regress.py などの python）が、残っていないかを数える。
#   powershell -NoProfile -ExecutionPolicy Bypass -File partsgen\tools\procs.ps1 [-Prio]
# ユーザー自身の Chrome と、AI のコーディングエージェントの node は、数えない（コマンドラインと、親子関係で見分ける）。落とすことはしない（数えるだけ）。
# -Prio を付けると、処理ごとの優先度も出す（撮影の最中に走らせて、優先度が下がっているかを見る）。
# このファイルは UTF-8（BOM 付き）。BOM が無いと、Windows PowerShell が日本語を読みまちがえる。
param([switch]$Prio)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$all = Get-CimInstance Win32_Process
$pat = '_chrome_prof|shoot\.mjs|uicheck\.mjs|perfcheck\.mjs|probe\.mjs|regress\.py|seqshoot\.py|fidscale\.py|fidelity\.py'
$mine = @{}
foreach ($p in $all) { if ($p.Name -match '^(chrome|node|python|msedge)' -and $p.CommandLine -match $pat) { $mine[[int]$p.ProcessId] = $p } }
# 子・孫（Chrome の描画用の子プロセスなど）も足す
$grew = $true
while ($grew) {
  $grew = $false
  foreach ($p in $all) {
    if (-not $mine.ContainsKey([int]$p.ProcessId) -and $mine.ContainsKey([int]$p.ParentProcessId) -and $p.Name -notmatch '^(conhost|powershell)') { $mine[[int]$p.ProcessId] = $p; $grew = $true }
  }
}
$m = @($mine.Values)
"撮影の処理: " + $m.Count + " 個（chrome " + @($m | Where-Object Name -match 'chrome|msedge').Count + "・node " + @($m | Where-Object Name -match 'node').Count + "・python " + @($m | Where-Object Name -match 'python').Count + "）"
if ($Prio) {
  foreach ($p in ($m | Sort-Object Name)) {
    $g = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
    if ($g) { "{0,-12} pid {1,-7} 優先度 {2}" -f $p.Name, $p.ProcessId, $g.PriorityClass }
  }
}
