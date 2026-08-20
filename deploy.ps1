# ===========================================================================
# Script de Deploy — Agente Comercial IA · CIME Power Systems
#
# Uso:
#   .\deploy.ps1              → Despliega en entorno 'dev' (por defecto)
#   .\deploy.ps1 -Env staging → Despliega en entorno 'staging'
#   .\deploy.ps1 -Env prod    → Despliega en entorno 'prod'
#   .\deploy.ps1 -ValidateOnly → Solo valida el template sin desplegar
#
# Prerrequisitos:
#   1. AWS SAM CLI instalado: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
#   2. AWS CLI configurado con credenciales válidas (aws configure)
#   3. Python 3.11 instalado y accesible en PATH
#   4. Valores reales en samconfig.toml (reemplazar PLACEHOLDERs)
# ===========================================================================

param(
    [ValidateSet("dev", "staging", "prod")]
    [string]$Env = "dev",

    [switch]$ValidateOnly,
    [switch]$SkipBuild,
    [switch]$Guided
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Colores para output
# ---------------------------------------------------------------------------
function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "   [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "   [ERROR] $msg" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# Verificar prerrequisitos
# ---------------------------------------------------------------------------
Write-Step "Verificando prerrequisitos..."

# SAM CLI
$samVersion = $null
try { $samVersion = (sam --version 2>&1) } catch {}
if (-not $samVersion) {
    Write-Err "AWS SAM CLI no encontrado. Instalar desde:"
    Write-Host "   https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"
    exit 1
}
Write-Ok "SAM CLI: $samVersion"

# AWS CLI
$awsVersion = $null
try { $awsVersion = (aws --version 2>&1) } catch {}
if (-not $awsVersion) {
    Write-Err "AWS CLI no encontrado. Instalar desde:"
    Write-Host "   https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
}
Write-Ok "AWS CLI: $awsVersion"

# Python
$pythonVersion = $null
try { $pythonVersion = (python --version 2>&1) } catch {}
if (-not $pythonVersion) {
    Write-Err "Python no encontrado en PATH."
    exit 1
}
Write-Ok "Python: $pythonVersion"

# Verificar credenciales AWS
Write-Step "Verificando credenciales AWS..."
try {
    $identity = aws sts get-caller-identity 2>&1 | ConvertFrom-Json
    Write-Ok "Cuenta: $($identity.Account) | Usuario: $($identity.Arn)"
} catch {
    Write-Err "No se pudieron verificar las credenciales AWS."
    Write-Host "   Ejecutar: aws configure"
    exit 1
}

# ---------------------------------------------------------------------------
# Validar template
# ---------------------------------------------------------------------------
Write-Step "Validando template SAM..."
sam validate --lint
if ($LASTEXITCODE -ne 0) {
    Write-Err "El template tiene errores de validacion. Corregir antes de continuar."
    exit 1
}
Write-Ok "Template valido."

if ($ValidateOnly) {
    Write-Host "`nValidacion completada exitosamente. No se despliega (-ValidateOnly)." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# Verificar PLACEHOLDERs en samconfig.toml
# ---------------------------------------------------------------------------
Write-Step "Verificando configuracion para entorno '$Env'..."

$samconfig = Get-Content "samconfig.toml" -Raw
if ($samconfig -match "PLACEHOLDER") {
    Write-Warn "samconfig.toml contiene valores PLACEHOLDER."
    Write-Host "   Reemplazar PLACEHOLDER_AGENT_ID y PLACEHOLDER_ALIAS_ID con valores reales."
    Write-Host "   Estos se obtienen del stack agentcore_runtime_config desplegado."
    Write-Host ""
    $continue = Read-Host "   Continuar de todas formas? (s/N)"
    if ($continue -ne "s" -and $continue -ne "S") {
        Write-Host "Deploy cancelado." -ForegroundColor Yellow
        exit 0
    }
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
if (-not $SkipBuild) {
    Write-Step "Construyendo artefactos (sam build)..."
    sam build --config-env $Env
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Error en sam build. Revisar la salida anterior."
        exit 1
    }
    Write-Ok "Build completado."
} else {
    Write-Warn "Build omitido (-SkipBuild). Usando artefactos previos."
}

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
Write-Step "Desplegando en entorno '$Env'..."

if ($Guided) {
    sam deploy --guided --config-env $Env
} else {
    sam deploy --config-env $Env
}

if ($LASTEXITCODE -ne 0) {
    Write-Err "Error en sam deploy. Revisar la salida anterior."
    exit 1
}

# ---------------------------------------------------------------------------
# Mostrar outputs
# ---------------------------------------------------------------------------
Write-Step "Deploy completado exitosamente!"
Write-Host ""
Write-Host "  Entorno: $Env" -ForegroundColor White
Write-Host ""

$stackName = "cime-webhook-$Env"
Write-Host "  Obteniendo URLs del stack '$stackName'..." -ForegroundColor Gray

try {
    $outputs = aws cloudformation describe-stacks --stack-name $stackName --query "Stacks[0].Outputs" 2>&1 | ConvertFrom-Json

    foreach ($output in $outputs) {
        Write-Host "  $($output.OutputKey): " -NoNewline -ForegroundColor White
        Write-Host "$($output.OutputValue)" -ForegroundColor Green
    }
} catch {
    Write-Warn "No se pudieron obtener los outputs. Verificar en la consola de CloudFormation."
}

Write-Host ""
Write-Host "  Siguiente paso: Copiar el WebhookEndpoint y configurarlo en Zapier." -ForegroundColor Cyan
Write-Host "  Ver: docs/zapier-setup.md" -ForegroundColor Gray
Write-Host ""
