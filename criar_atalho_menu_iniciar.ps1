$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $Root "DocFlow_Manager.pyw"
$Icon = Join-Path $Root "assets\docflow_manager_icon.ico"

$PythonExe = $null
try { $PythonExe = (Get-Command python.exe -ErrorAction Stop).Source } catch {}
if (-not $PythonExe) {
    try {
        $PyLauncher = (Get-Command py.exe -ErrorAction Stop).Source
        $PythonExe = (& $PyLauncher -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
    } catch {}
}
if (-not $PythonExe) { throw "Python nao foi encontrado no PATH." }

$PythonW = Join-Path (Split-Path -Parent $PythonExe) "pythonw.exe"
if (-not (Test-Path $PythonW)) { throw "pythonw.exe nao foi encontrado ao lado de: $PythonExe" }

$StartMenu = [Environment]::GetFolderPath("StartMenu")
$Programs = Join-Path $StartMenu "Programs"
$ShortcutPath = Join-Path $Programs "DocFlow Manager.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonW
$Shortcut.Arguments = '"' + $Launcher + '"'
$Shortcut.WorkingDirectory = $Root
if (Test-Path $Icon) { $Shortcut.IconLocation = $Icon + ",0" }
$Shortcut.Description = "DocFlow Manager"
$Shortcut.Save()

Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show(
    "Atalho criado no Menu Iniciar.\n\nEle aponta DIRETAMENTE para pythonw.exe e abre o DocFlow Manager sem console e sem flash de .bat/cmd.",
    "DocFlow Manager",
    "OK",
    "Information"
) | Out-Null
