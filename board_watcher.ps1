# 物件ボード連絡帳の見張り役（Cowork → Claude Code）。2026-09-23 Cowork 指示-20260923-1110・オーナー承認済み。
#
# Google Drive の「物件ボード連絡帳」フォルダ（Drive ID: 1WA4nGMWNz1HwAhcUvDed-pGVLieUIxRQ、
# Google Drive for Desktop でPCに見えている場所。例: H:\マイドライブ\物件ボード連絡帳）を見張り、
# 新しい「指示-<番号>.md」が置かれ、同じ番号の「報告-<番号>.md」がまだ無ければ、
# daikichi-mapper のフォルダを作業フォルダにして claude -p を1回実行する
# （指示を読んで実行し、報告-<番号>.md を連絡帳に置き、指示に書かれた合図を発火する）。
#
# 2026-09-23 Cowork 指示-20260923-1125 で変更：新しい会話ではなく、**地図を作った既存の会話の続き**として動かす。
# 使う会話のセッションIDは logs\session_id.txt の1行目（オーナーが後で差し替えられる）。
# 再開できなかったとき（IDが無い・上限・壊れている等）は --continue（このフォルダの直近の会話）→
# それもだめなら新しい会話、の順に切り替え、どの方法で動いたかをログに残す。
#
# mervari-assist の inbox_watcher.ps1 と同じ作りの別スクリプト。mervari-assist 側には手を触れていない
# （watchdog.py の生存確認に1行ぶん足しただけ）。取り違えを防ぐため、名前・目印・Mutex はすべて別にしてある。
#
# - 「取消済み-」「保留-」など「指示-」で始まらない名前のファイルは対象外（名前を「指示-…」に直せば拾う）
# - ファイルの大きさが落ち着くまで待ってから実行（Drive の同期の途中で読まない）
# - 処理中の目印 logs\inbox\<番号>.processing と完了の目印 <番号>.done で二重実行を防ぐ。同時に動かす claude は1つだけ
# - 起動時に、まだ報告の無い指示が残っていればそれも処理する（PC が止まっている間に置かれた分）
# - Drive の仮想ドライブでは変更の知らせが届かないことがあるので、10分ごとにフォルダの一覧も見直す（PC 内の一覧を見るだけ）
# - 記録は logs\board_watcher-日付.log、claude の出力は logs\inbox\<番号>.log
# - Windows ログオン時にスタートアップのショートカット（board_start.pyw 経由、窓を出さない）で起動する
#
# 見張るフォルダは board_folder.txt（このファイルと同じ場所）の1行目。無ければ自動で探して書き込む。

$ErrorActionPreference = "Continue"
$Base = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Base "logs"
$InboxDir = Join-Path $LogDir "inbox"
New-Item -ItemType Directory -Force -Path $InboxDir | Out-Null
function Resolve-Claude {
    # claude.exe の場所を毎回探す（Claude Code の更新・入れ替えで場所が変わっても止まらないように。2026-09-24 追加）
    $cands = @(
        (Join-Path $env:APPDATA "npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\claude.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\claude\claude.exe")
    )
    $cmd = Get-Command claude.exe -ErrorAction SilentlyContinue
    if ($cmd) { $cands += $cmd.Source }
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}
$Claude = Resolve-Claude
if (-not $Claude) { $Claude = Join-Path $env:APPDATA "npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe" }
$SettingsFile = Join-Path $Base "board_watcher_permissions.json"  # 許可設定。.claude\ の中は自動編集が禁じられているので、この場所に置いている
$FolderFile = Join-Path $Base "board_folder.txt"
$SessionFile = Join-Path $LogDir "session_id.txt"  # 続きとして使う会話のセッションID（1行目）。オーナーが差し替え可
$FolderName = "物件ボード連絡帳"
$RunTimeoutMin = 240   # 地図データの作り直しは時間がかかるので mervari 側（120分）より長くとる
$RescanSec = 600

function Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path (Join-Path $LogDir ("board_watcher-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))) -Value $line -Encoding UTF8
}

# 二重起動を防ぐ（mervari-assist の見張り役とは別の名前）
$created = $false
$mutex = [System.Threading.Mutex]::new($true, "Global\daikichi-mapper-board-watcher", [ref]$created)  # New-Object では [ref] が効かない
if (-not $created) { exit 0 }

function Find-Folder {
    if (Test-Path $FolderFile) {
        $p = (Get-Content $FolderFile -Encoding UTF8 | Select-Object -First 1).Trim()
        if ($p -and (Test-Path $p)) { return $p }
    }
    $roots = @()
    foreach ($d in (Get-PSDrive -PSProvider FileSystem)) { $roots += $d.Root }
    $roots += $env:USERPROFILE
    foreach ($r in $roots) {
        foreach ($sub in @("マイドライブ\$FolderName", "My Drive\$FolderName", "Google Drive\マイドライブ\$FolderName", "Google Drive\My Drive\$FolderName")) {
            $p = Join-Path $r $sub
            if (Test-Path $p) {
                Set-Content -Path $FolderFile -Value $p -Encoding UTF8
                return $p
            }
        }
    }
    return $null
}

function Get-SessionId {
    # 続きとして使う会話のセッションID。指示を見つけるたびに読み直すので、
    # オーナーが session_id.txt を書き替えれば次の指示からそちらの会話になる（見張り役の再起動は不要）。
    if (-not (Test-Path $SessionFile)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $SessionFile -Encoding UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith("#")) { continue }
        if ($t -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') { return $t }
        Log "session_id.txt の行がセッションIDの形ではないので読み飛ばす: $t"
    }
    return $null
}

function Invoke-Claude($extraArgs, $prompt, $folder) {
    # claude を1回動かして、終了コード・出力・かかった秒数を返す
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Claude
    $psi.Arguments = ("-p `"$prompt`" --settings `"$SettingsFile`" --add-dir `"$folder`" --permission-mode acceptEdits " + $extraArgs).Trim()
    $psi.WorkingDirectory = $Base
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $started = Get-Date
    $p = [System.Diagnostics.Process]::Start($psi)
    $stdout = $p.StandardOutput.ReadToEndAsync()
    $stderr = $p.StandardError.ReadToEndAsync()
    $timedOut = $false
    if (-not $p.WaitForExit($RunTimeoutMin * 60 * 1000)) { $p.Kill(); $timedOut = $true }
    return @{
        Code    = $p.ExitCode
        Out     = $stdout.Result
        Err     = $stderr.Result
        Seconds = [int]((Get-Date) - $started).TotalSeconds
        TimedOut = $timedOut
    }
}

function Wait-Stable($path) {
    # 2秒おきに大きさを見て、3回続けて同じ（かつ0でない）なら書き終わったとみなす。最大2分
    $last = -1; $same = 0
    for ($i = 0; $i -lt 60; $i++) {
        try { $size = (Get-Item -LiteralPath $path -ErrorAction Stop).Length } catch { return $false }
        if ($size -gt 0 -and $size -eq $last) { $same++ } else { $same = 0 }
        if ($same -ge 3) { return $true }
        $last = $size
        Start-Sleep -Seconds 2
    }
    return $false
}

function Process-Instruction($folder, $path) {
    $name = [System.IO.Path]::GetFileName($path)
    if ($name -notmatch '^指示-(.+)\.md$') { return }
    $num = $Matches[1]
    $report = Join-Path $folder ("報告-{0}.md" -f $num)
    $done = Join-Path $InboxDir ("{0}.done" -f $num)
    $flag = Join-Path $InboxDir ("{0}.processing" -f $num)
    $failed = Join-Path $InboxDir ("{0}.failed" -f $num)
    if ((Test-Path -LiteralPath $report) -or (Test-Path -LiteralPath $done)) { return }
    $fails = 0
    if (Test-Path -LiteralPath $failed) { $fails = [int](Get-Content -LiteralPath $failed | Select-Object -First 1) }
    if ($fails -ge 2) { return }  # 2回実行しても報告が出なかった指示は、もう自動では実行しない（ログを見て人が判断）
    if (Test-Path -LiteralPath $flag) {
        # 前回の実行中に PC が止まった等で残った目印。時間切れの時間より古ければ、古いとみなしてやり直す
        if (((Get-Date) - (Get-Item -LiteralPath $flag).LastWriteTime).TotalMinutes -lt $RunTimeoutMin) { return }
        Log "古い処理中の目印を消してやり直す: $num"
        Remove-Item -LiteralPath $flag -Force
    }
    if (-not (Wait-Stable $path)) { Log "ファイルが落ち着かない／読めないので今回は見送り: $name"; return }
    if (Test-Path -LiteralPath $report) { return }
    $found = Resolve-Claude
    if (-not $found) { Log "claude が見つからない（npm・.local\\bin・PATH を探した）: $Claude"; return }
    $script:Claude = $found
    Set-Content -LiteralPath $flag -Value (Get-Date -Format s) -Encoding UTF8
    $prompt = "連絡帳の $path を読んで、書かれているとおりに実行し、完了したら同じ番号の報告ファイル（$report）を連絡帳に置き、指示に書かれた合図を送ってください"
    $out = Join-Path $InboxDir ("{0}.log" -f $num)
    Log "実行開始: $name"

    # どの会話で動かすか。上から順に試し、始められなかったときだけ次に切り替える
    $ways = @()
    $sid = Get-SessionId
    if ($sid) { $ways += @{ Name = "地図の会話を再開（--resume $sid）"; Args = "--resume `"$sid`"" } }
    else { Log "session_id.txt にセッションIDが無いので、--continue から始める" }
    $ways += @{ Name = "このフォルダの直近の会話を再開（--continue）"; Args = "--continue" }
    $ways += @{ Name = "新しい会話"; Args = "" }

    # 「会話を始められなかった」ことを示す出力。これに当たるか、すぐ終わったときだけ次の方法に切り替える
    # （途中まで作業が進んでいたら、やり直すと二重作業になるため）
    $startFailPattern = 'No conversation found|Could not find|No such session|Invalid session|session .{0,40}not found|too (large|long)|usage limit|rate limit|quota|context (window|limit)|ENOENT'

    $ok = $false
    try {
        Set-Content -LiteralPath $out -Value ("実行開始 {0}  指示: {1}" -f (Get-Date -Format s), $name) -Encoding UTF8
        for ($i = 0; $i -lt $ways.Count; $i++) {
            $way = $ways[$i]
            Log ("試す: {0}" -f $way.Name)
            $r = Invoke-Claude $way.Args $prompt $folder
            if ($r.TimedOut) { Log "時間切れ（$RunTimeoutMin 分）で止めた: $name" }
            Add-Content -LiteralPath $out -Encoding UTF8 -Value (
                ("`n===== {0} / 終了コード {1} / {2}秒 =====`n" -f $way.Name, $r.Code, $r.Seconds) +
                $r.Out + "`n--- stderr ---`n" + $r.Err)
            $ok = Test-Path -LiteralPath $report
            Log ("実行終了: {0}（{1}、終了コード {2}、{3}秒、報告ファイル {4}）" -f $name, $way.Name, $r.Code, $r.Seconds, $(if ($ok) { "あり" } else { "なし" }))
            if ($ok) { Log ("この方法で動きました: {0}" -f $way.Name); break }
            if ($i -eq $ways.Count - 1) { break }
            $text = $r.Out + $r.Err
            $startFailed = ($text -match $startFailPattern) -or ($r.Seconds -lt 180 -and $r.Code -ne 0)
            if (-not $startFailed) {
                Log "会話は始まったが報告が出なかった。二重作業を避けるため、別の方法への切り替えはしない"
                break
            }
            Log ("会話を始められなかったようなので、次の方法に切り替える → {0}" -f $ways[$i + 1].Name)
        }
        if ($ok) { Set-Content -LiteralPath $done -Value (Get-Date -Format s) -Encoding UTF8 }
        else {
            # 報告が出なかった（未ログイン等）。2回までやり直す（次の見直しは10分後）
            Set-Content -LiteralPath $failed -Value ($fails + 1) -Encoding UTF8
            $brief = ((Get-Content -LiteralPath $out -Raw -Encoding UTF8) -replace "\s+", " ").Trim()
            if ($brief.Length -gt 300) { $brief = $brief.Substring($brief.Length - 300) }
            Log ("報告が出なかった（{0}回目）。出力の終わり: {1}" -f ($fails + 1), $brief)
        }
    } catch {
        Log "実行に失敗: $name $($_.Exception.Message)"
    } finally {
        Remove-Item -LiteralPath $flag -Force -ErrorAction SilentlyContinue
    }
}

function Scan($folder) {
    Get-ChildItem -LiteralPath $folder -Filter "指示-*.md" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | ForEach-Object { Process-Instruction $folder $_.FullName }
}

Log "見張り役を起動（claude: $Claude）"
$folder = $null
while (-not $folder) {
    $folder = Find-Folder
    if (-not $folder) {
        Log "見張るフォルダ（$FolderName）が見つからない。Google Drive for Desktop の準備を待つ（10分後にもう一度探す）"
        Start-Sleep -Seconds $RescanSec
    }
}
Log "見張るフォルダ: $folder"

# 既存分（報告の無い指示）を先に処理
Scan $folder

$watcher = New-Object System.IO.FileSystemWatcher $folder, "指示-*.md"
$watcher.IncludeSubdirectories = $false
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, LastWrite, Size'
$watcher.EnableRaisingEvents = $true
Register-ObjectEvent $watcher Created -SourceIdentifier boardCreated | Out-Null
Register-ObjectEvent $watcher Renamed -SourceIdentifier boardRenamed | Out-Null
Register-ObjectEvent $watcher Changed -SourceIdentifier boardChanged | Out-Null

$lastScan = Get-Date
while ($true) {
    $ev = Wait-Event -Timeout 30
    if ($ev) {
        $path = $ev.SourceEventArgs.FullPath
        Remove-Event -EventIdentifier $ev.EventIdentifier
        # 同じファイルの続けざまの知らせはまとめる
        Get-Event -ErrorAction SilentlyContinue | Where-Object { $_.SourceEventArgs.FullPath -eq $path } | ForEach-Object { Remove-Event -EventIdentifier $_.EventIdentifier }
        Process-Instruction $folder $path
    }
    if (((Get-Date) - $lastScan).TotalSeconds -ge $RescanSec) {
        if (-not (Test-Path -LiteralPath $folder)) { Log "見張るフォルダが見えなくなった（Drive の同期停止？）: $folder" }
        else { Scan $folder }
        $lastScan = Get-Date
    }
}
