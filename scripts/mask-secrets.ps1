# mask-secrets.ps1 - mask secret VALUES in a text file without ever printing them.
# Usage: powershell -File scripts\mask-secrets.ps1 -In <src> -Out <dst>
# Masks: provider tokens (telegram bot / anthropic / polza / jwt / github),
# private key blocks, key=value and key: value secrets (labels in EN and RU;
# RU labels are \uXXXX escapes so this file stays ASCII-only and PS 5.1-safe -
# a UTF-8 .ps1 without BOM is read as ANSI by PS 5.1 and breaks on Cyrillic).
# Prints only COUNTS of remaining suspicious patterns, never values.
# Known false positive: "root:group" file-permission snippets after secret labels.
param(
  [Parameter(Mandatory = $true)][string]$In,
  [Parameter(Mandatory = $true)][string]$Out
)
$t = [IO.File]::ReadAllText($In, [Text.Encoding]::UTF8)

# 1. private key blocks
$t = [regex]::Replace($t, '(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', '***PRIVATE-KEY-MASKED***')
# 2. provider tokens / known formats
$t = [regex]::Replace($t, '\b\d{8,11}:[A-Za-z0-9_-]{30,}', '***BOT-TOKEN***')
$t = [regex]::Replace($t, 'sk-ant-[A-Za-z0-9_-]{8,}', '***ANTHROPIC-KEY***')
$t = [regex]::Replace($t, 'pza_[A-Za-z0-9_-]{8,}', '***POLZA-KEY***')
$t = [regex]::Replace($t, 'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}', '***JWT***')
$t = [regex]::Replace($t, '(ghp_|gho_|ghu_|ghs_|github_pat_)[A-Za-z0-9_]{10,}', '***GITHUB-TOKEN***')
# 3. named secrets (EN labels): key=value / key: value
$t = [regex]::Replace($t, '(?im)((?:api[_\-]?key|access[_\-]?key|client[_\-]?secret|auth[_\-]?token|token|secret|password|passwd|passphrase|pwd|credential)[''\x22 ]{0,4}[:=][ \t]{0,4})(\S{4,})', '$1***MASKED***')
# 4. named secrets (RU labels): password=parol, token=token, secret=sekret, key=klyuch
$t = [regex]::Replace($t, '(?im)((?:\u043f\u0430\u0440\u043e\u043b\u044c|\u043f\u0430\u0440\u043e\u043b\u044f|\u0442\u043e\u043a\u0435\u043d|\u0442\u043e\u043a\u0435\u043d\u0430|\u0441\u0435\u043a\u0440\u0435\u0442|\u0441\u0435\u043a\u0440\u0435\u0442\u0430|\u043a\u043b\u044e\u0447|\u043a\u043b\u044e\u0447\u0430)[^\r\n:]{0,24}?[:=][ \t]{0,4})(\S{4,})', '$1***MASKED***')
# 5. bearer
$t = [regex]::Replace($t, '(?i)(bearer[ \t]+)(\S{10,})', '$1***MASKED***')
[IO.File]::WriteAllText($Out, $t, (New-Object System.Text.UTF8Encoding($false)))

# blind pass: lines with a secret label and an unmasked value -> mask after first : or =
$lines = [IO.File]::ReadAllLines($Out, [Text.Encoding]::UTF8)
$susp = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
  $l = $lines[$i]
  if ($l -notmatch 'MASKED|\*\*\*' -and $l -match '(?i)(token|secret|password|credential|pwd|api[_\-]?key|access[_\-]?key|\u043f\u0430\u0440\u043e\u043b|\u0442\u043e\u043a\u0435\u043d|\u0441\u0435\u043a\u0440\u0435\u0442)') {
    $eq = $l.IndexOf('=')
    $co = $l.IndexOf(':')
    $idx = $eq
    if ($idx -lt 0 -or ($co -ge 0 -and $co -lt $idx)) { $idx = $co }
    if ($idx -gt 0 -and $l.Substring($idx + 1) -match '\S{6,}') {
      $lines[$i] = $l.Substring(0, $idx + 1) + ' ***MASKED***'
      $susp++
    }
  }
}
Write-Host ('blind-masked lines: ' + $susp)
[IO.File]::WriteAllLines($Out, $lines, (New-Object System.Text.UTF8Encoding($false)))

# audit: counts only, values are never printed
$check = [IO.File]::ReadAllText($Out, [Text.Encoding]::UTF8)
$pats = [ordered]@{
  'bot-token'   = '\b\d{8,11}:[A-Za-z0-9_-]{30,}'
  'anthropic'   = 'sk-ant-[A-Za-z0-9_-]{8,}'
  'polza'       = 'pza_[A-Za-z0-9_-]{8,}'
  'jwt'         = 'eyJ[A-Za-z0-9_-]{15,}\.'
  'privkey'     = 'BEGIN [A-Z ]*PRIVATE KEY'
  'bearer'      = '(?i)bearer[ \t]+(?!)[A-Za-z0-9._\-]{10,}'
  'bare-secret' = '(?im)(?:token|secret|password|\u043f\u0430\u0440\u043e\u043b|\u0442\u043e\u043a\u0435\u043d)[^\r\n]{0,24}?[:=][ \t]{0,4}(?!\*)(\S{8,})'
}
foreach ($k in $pats.Keys) {
  $m = [regex]::Matches($check, $pats[$k])
  Write-Host ($k + ': ' + $m.Count)
}
Write-Host ('out bytes: ' + (Get-Item $Out).Length)