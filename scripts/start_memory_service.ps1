param(
  [int]$Port = 8091,
  [string]$Token = $env:MEMORY_SERVICE_TOKEN,
  [string]$RoleSecret = $env:MEMORY_ROLE_SECRET,
  [string]$Database = "memory-service/memory.sqlite3",
  [ValidateSet("local", "mem_pro")][string]$Backend = $env:MEMORY_BACKEND
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Token) -or [string]::IsNullOrWhiteSpace($RoleSecret)) { throw "MEMORY_SERVICE_TOKEN and MEMORY_ROLE_SECRET are required" }
$env:MEMORY_SERVICE_TOKEN = $Token
$env:MEMORY_SERVICE_HOST = "127.0.0.1"
$env:MEMORY_SERVICE_PORT = "$Port"
$env:MEMORY_SERVICE_DB = $Database
if ([string]::IsNullOrWhiteSpace($Backend)) { $Backend = "local" }
$env:MEMORY_BACKEND = $Backend
$env:MEMORY_PROVIDER_URL = "http://127.0.0.1:$Port"
python -B memory-service/memory_service.py
