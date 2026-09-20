param([switch]$PrepareDemo)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Crie o ambiente com python -m venv venv e instale requirements.txt antes de iniciar.'
}

& $pythonPath manage.py migrate --settings=nabio_elege.local_settings
if ($LASTEXITCODE -ne 0) { throw 'Falha ao aplicar as migrações locais.' }

if ($PrepareDemo) {
    $demoSecret = Read-Host 'Senha dos dois usuários fictícios (mínimo 12 caracteres)' -AsSecureString
    $demoCredential = New-Object System.Net.NetworkCredential('', $demoSecret)
    try {
        & $pythonPath manage.py seed_demo --password $demoCredential.Password --settings=nabio_elege.local_settings
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar usuários de demonstração.' }
        & $pythonPath manage.py seed_political_demo --settings=nabio_elege.local_settings
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar a demonstração eleitoral.' }
    } finally {
        $demoCredential = $null
        $demoSecret = $null
    }
}

Write-Host 'Demonstração local: http://127.0.0.1:8020'
Write-Host 'Contas fictícias: demo.gestor e demo.revisor. Nunca use esta configuração em produção.'
& $pythonPath manage.py runserver 127.0.0.1:8020 --settings=nabio_elege.local_settings
