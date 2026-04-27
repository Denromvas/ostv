param(
    [string]$VMName     = "OsTv",
    [int]   $VCpu       = 2,
    [int64] $DiskBytes  = 16GB,
    [int64] $RamMinBytes = 1GB,
    [int64] $RamMaxBytes = 2GB,
    [string]$SwitchName = "Default Switch",
    [string]$WorkDir    = "C:\Hyper-V\OsTv"
)

# Run as Administrator. Requires Hyper-V enabled on Win11 Pro/Enterprise.
# Expects $WorkDir contains:
#   jammy.vhdx   — Ubuntu 22.04 generic cloud image converted from .img to .vhdx
#                  (e.g. via WSL: qemu-img convert -O vhdx jammy.img jammy.vhdx)
#   cidata.iso   — cloud-init seed built from user-data + meta-data
#                  (e.g. on Linux: cloud-localds cidata.iso user-data meta-data)

$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

if (Get-VM -Name $VMName -ErrorAction SilentlyContinue) {
    Stop-VM $VMName -TurnOff -Force -ErrorAction SilentlyContinue
    Remove-VM $VMName -Force
}

$Vhdx     = "$WorkDir\jammy.vhdx"
$BootVhdx = "$WorkDir\$VMName-boot.vhdx"
$Cidata   = "$WorkDir\cidata.iso"

if (-not (Test-Path $Vhdx))   { throw "$Vhdx not found - convert from cloud-images.ubuntu.com first" }
if (-not (Test-Path $Cidata)) { throw "$Cidata not found - generate via cloud-localds" }

Step "1/4 copy vhdx to boot disk"
Copy-Item $Vhdx $BootVhdx -Force

Step "2/4 resize to $($DiskBytes/1GB) GB"
Resize-VHD -Path $BootVhdx -SizeBytes $DiskBytes

Step "3/4 create Gen2 VM with cidata DVD"
New-VM -Name $VMName -Generation 2 -MemoryStartupBytes $RamMinBytes `
    -SwitchName $SwitchName -VHDPath $BootVhdx | Out-Null
Set-VMMemory   -VMName $VMName -DynamicMemoryEnabled 1 `
               -StartupBytes $RamMinBytes -MinimumBytes $RamMinBytes -MaximumBytes $RamMaxBytes
Set-VMProcessor -VMName $VMName -Count $VCpu
Set-VMFirmware  -VMName $VMName -EnableSecureBoot Off
Add-VMDvdDrive  -VMName $VMName -Path $Cidata
Set-VM          -Name   $VMName -AutomaticCheckpointsEnabled $false -CheckpointType Disabled

Step "4/4 start"
Start-VM -Name $VMName

Write-Host ""
Write-Host "VM started. cloud-init runs unattended OsTv install (~5-15 min)."
Write-Host "  Get-VMNetworkAdapter -VMName $VMName | Select -ExpandProperty IPAddresses"
Write-Host "  ssh tv@<ip>  # default password: ostv (CHANGE IT after first login)"
