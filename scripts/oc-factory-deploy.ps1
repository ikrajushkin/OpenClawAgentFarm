# oc-factory-deploy.ps1 - deploy the agent factory (OPF-8) to oc-node1 (E4, 2026-10-21).
# Installs code + questionnaires to /usr/local/lib/oc-factory/ (wrapper /usr/local/bin/oc-factory),
# drift control (oc-factory-drift.sh + /etc/cron.d/oc-factory + zabbix UserParameter), then runs
# factory validate + export --check (drift must be 0).
# Sources: scripts/oc-agent-factory.py, agents/*.yaml, infra/factory/*, infra/cron/oc-factory,
# infra/zabbix/openclaw-factory.conf. Details: docs/ (restore-and-deploy doc, agents/README.md).
param([string]$Server = "root@45.91.237.204")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = "/root/oc-factory-deploy"

# LF-normalized temp copy (CRLF breaks bash; plan section 9 pitfall).
function Copy-Lf([string]$Src, [string]$DstName) {
    $txt = [System.IO.File]::ReadAllText($Src) -replace "`r`n", "`n"
    $tmp = Join-Path $env:TEMP $DstName
    [System.IO.File]::WriteAllText($tmp, $txt, (New-Object System.Text.UTF8Encoding $false))
    return $tmp
}

plink -ssh -batch $Server "rm -rf $stage; mkdir -p $stage/agents"
if ($LASTEXITCODE -ne 0) { throw "ssh to $Server failed" }

pscp -batch (Join-Path $repo "scripts\oc-agent-factory.py") "${Server}:$stage/oc-agent-factory.py"
if ($LASTEXITCODE -ne 0) { throw "pscp factory failed" }
$agents = (Get-ChildItem -Path (Join-Path $repo "agents") -Filter *.yaml).FullName
pscp -batch $agents "${Server}:$stage/agents/"
if ($LASTEXITCODE -ne 0) { throw "pscp agents failed" }

pscp -batch (Copy-Lf (Join-Path $repo "infra\factory\oc-factory-drift.sh") "oc-factory-drift.sh") "${Server}:$stage/oc-factory-drift.sh"
pscp -batch (Copy-Lf (Join-Path $repo "infra\factory\oc-factory-install.sh") "oc-factory-install.sh") "${Server}:$stage/oc-factory-install.sh"
pscp -batch (Copy-Lf (Join-Path $repo "infra\cron\oc-factory") "cron-oc-factory") "${Server}:$stage/cron-oc-factory"
pscp -batch (Copy-Lf (Join-Path $repo "infra\zabbix\openclaw-factory.conf") "openclaw-factory.conf") "${Server}:$stage/openclaw-factory.conf"
if ($LASTEXITCODE -ne 0) { throw "pscp infra failed" }

plink -ssh -batch $Server "bash $stage/oc-factory-install.sh $stage"
if ($LASTEXITCODE -ne 0) { throw "install failed" }

plink -ssh -batch $Server "/usr/local/bin/oc-factory export --check --config /srv/openclaw/.openclaw/openclaw.json --agents-dir /usr/local/lib/oc-factory/agents"
if ($LASTEXITCODE -ne 0) { throw "export --check failed (drift or error)" }

plink -ssh -batch $Server "rm -rf $stage"
Write-Host "oc-factory deployed to $Server; export --check = 0 (no drift)"