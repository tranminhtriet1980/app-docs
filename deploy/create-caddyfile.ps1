# Tao deploy\Caddyfile cho Docker Caddy
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "deploy\Caddyfile"

New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null

$content = @"
{
	admin off
}

:443 {
	tls internal

	@api path /api/*
	handle @api {
		reverse_proxy backend:8000
	}

	@backend_misc path /health /docs /docs/* /openapi.json /redoc /redoc/*
	handle @backend_misc {
		reverse_proxy backend:8000
	}

	handle {
		reverse_proxy frontend:3000
	}
}
"@

[System.IO.File]::WriteAllText($Out, $content, [System.Text.UTF8Encoding]::new($false))
Write-Host "Created: $Out"
Write-Host "Exists: $(Test-Path $Out)"
