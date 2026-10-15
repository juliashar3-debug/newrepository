param([string]$InputPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
$application = $null
$presentation = $null
$ownedEmptyApplication = $false
try {
    $application = New-Object -ComObject PowerPoint.Application
    $ownedEmptyApplication = ($application.Presentations.Count -eq 0)
    $presentation = $application.Presentations.Open($InputPath, -1, 0, 0)
    $presentation.ExportAsFixedFormat($OutputPath, 2)
} finally {
    if ($null -ne $presentation) {
        $presentation.Close()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation)
    }
    if ($null -ne $application) {
        if ($ownedEmptyApplication -and $application.Presentations.Count -eq 0) { $application.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application)
    }
}
