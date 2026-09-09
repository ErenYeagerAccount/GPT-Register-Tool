$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$globalJson = Get-Content (Join-Path $repoRoot "global.json") -Raw | ConvertFrom-Json
$requiredSdk = [string]$globalJson.sdk.version
$candidates = @(
    (Join-Path $repoRoot ".dotnet\dotnet.exe"),
    "dotnet",
    (Join-Path $env:ProgramFiles "dotnet\dotnet.exe")
)

$dotnet = $null
foreach ($candidate in $candidates) {
    try {
        $command = Get-Command $candidate -ErrorAction Stop
        $hostPath = if ($command.Path) { $command.Path } else { $command.Source }
        $versionOutput = @(& $hostPath --version 2>&1)
        $hostExitCode = $LASTEXITCODE
        $version = ($versionOutput | Select-Object -First 1).ToString().Trim()
        if ($hostExitCode -eq 0 -and $version) {
            $dotnet = $hostPath
            break
        }
    } catch {
        continue
    }
}
if (-not $dotnet) {
    throw "No executable .NET host found; required SDK is $requiredSdk"
}

$requiredParts = $requiredSdk -split '\.'
$actualParts = $version -split '\.'
$rollForward = [string]$globalJson.sdk.rollForward
$sameMajorMinor = $requiredParts.Length -ge 2 -and $actualParts.Length -ge 2 -and
    $requiredParts[0] -eq $actualParts[0] -and
    $requiredParts[1] -eq $actualParts[1]
$sameFeatureBand = $sameMajorMinor -and $requiredParts.Length -ge 3 -and $actualParts.Length -ge 3 -and
    $requiredParts[2].Substring(0, 2) -eq $actualParts[2].Substring(0, 2)
# latestMinor/latestMajor let CI hosts (currently 10.0.401) run a newer 10.0 SDK
# than the pinned 10.0.300 feature band without failing preflight.
$compatibleFeatureBand = if ($rollForward -in @("latestMinor", "latestMajor")) {
    $sameMajorMinor
} else {
    $sameFeatureBand
}
if (-not $compatibleFeatureBand) {
    throw "Required .NET SDK feature band $requiredSdk, found $version at $dotnet"
}

$installed = @(& $dotnet --list-sdks 2>&1)
if ($LASTEXITCODE -ne 0 -or -not ($installed | Where-Object { $_ -match "^$([regex]::Escape($version))\s" })) {
    throw ".NET host at $dotnet runs but SDK $version is not listed as installed"
}

$pythonVersion = (& python --version 2>&1 | Select-Object -First 1).ToString().Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Python host is not executable"
}

$curlProbe = @(& python -c "import curl_cffi; from curl_cffi.requests.impersonate import BrowserType; print(curl_cffi.__version__); print(','.join(x.value for x in BrowserType))" 2>&1)
if ($LASTEXITCODE -ne 0 -or $curlProbe.Count -lt 2) {
    throw "curl_cffi profile probe failed; install requirements.txt in the isolated environment"
}
$curlVersion = [string]$curlProbe[0]
$curlVersionOk = $curlVersion -match '^0\.(15|16)(\.|$)'
if (-not $curlVersionOk) {
    throw "curl_cffi $curlVersion is unsupported; required 0.15.x or 0.16.x"
}
$requiredProfile = "chrome146"
$profiles = [string]$curlProbe[1] -split ','
if ($profiles -notcontains $requiredProfile) {
    throw "curl_cffi $curlVersion lacks required browser profile $requiredProfile"
}

Write-Host "Environment ready: Python $pythonVersion; curl_cffi $curlVersion ($requiredProfile); .NET SDK $version ($dotnet)"
