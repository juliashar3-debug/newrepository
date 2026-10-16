param([string]$InputPath, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$application = $null
$presentation = $null
$ownedEmptyApplication = $false
$stage = 'start'
$failed = $false
try {
    $InputPath = [IO.Path]::GetFullPath($InputPath)
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    if (-not [IO.File]::Exists($InputPath)) { throw 'Input presentation does not exist.' }
    $application = New-Object -ComObject PowerPoint.Application
    $ownedEmptyApplication = ($application.Presentations.Count -eq 0)
    $stage = 'open'
    $presentation = $application.Presentations.Open($InputPath, -1, 0, 0)
    $stage = 'save'
    # ppSaveAsPDF = 32. SaveAs avoids ExportAsFixedFormat's optional COM
    # PrintRange argument, which PowerShell cannot reliably bind when omitted.
    $presentation.SaveAs($OutputPath, 32)
    if (-not [IO.File]::Exists($OutputPath)) { throw 'PowerPoint did not write the PDF file.' }
} catch {
    $failed = $true
    $detail = $_.Exception.GetBaseException()
    $diagnostic = @{stage = $stage; message = $detail.Message; hresult = ('0x{0:X8}' -f $detail.HResult)}
    [Console]::Out.WriteLine('SMS_POWERPOINT_ERROR=' + ($diagnostic | ConvertTo-Json -Compress))
} finally {
    # Cleanup must not replace the export error or close the owner's other files.
    if ($null -ne $presentation) {
        try { $presentation.Close() } catch {}
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) } catch {}
    }
    if ($null -ne $application) {
        try {
            if ($ownedEmptyApplication -and $application.Presentations.Count -eq 0) { $application.Quit() }
        } catch {}
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application) } catch {}
    }
}
if ($failed) { exit 1 }
