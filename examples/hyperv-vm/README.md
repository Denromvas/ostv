# OsTv on Hyper-V — quickstart

Розгорнути OsTv kiosk як Hyper-V VM на Win11 Pro (з вмикненим Hyper-V).
Повністю unattended: 1 команда → cloud-init робить решту.

## Артефакти
- `user-data` — cloud-init: створює юзера `tv` з тимчасовим паролем `ostv`,
  ставить пакети, тягне latest OsTv release з GitHub і запускає `install.sh`
- `meta-data` — `instance-id` + hostname для NoCloud datasource
- `setup-ostv-vm.ps1` — створює Gen2 VM 2 vCPU / 1-2 GB RAM / 16 GB disk,
  attaches `jammy.vhdx` + `cidata.iso`, стартує

## Підготовка (на Linux або WSL)

```bash
# 1. Згенерувати cidata.iso
cd examples/hyperv-vm
sudo apt install cloud-image-utils    # або brew install cdrtools
cloud-localds cidata.iso user-data meta-data

# 2. Завантажити Ubuntu generic cloud image
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img

# 3. Конвертувати qcow2 → vhdx (Hyper-V Gen2)
sudo apt install qemu-utils
qemu-img convert -O vhdx -o subformat=dynamic jammy-server-cloudimg-amd64.img jammy.vhdx
```

## Запуск (PowerShell as Administrator на Win11 Pro)

```powershell
# Підготовка робочої директорії
mkdir C:\Hyper-V\OsTv
copy jammy.vhdx        C:\Hyper-V\OsTv\
copy cidata.iso        C:\Hyper-V\OsTv\
copy setup-ostv-vm.ps1 C:\Hyper-V\OsTv\

# Запуск (PowerShell з правами Admin)
Set-ExecutionPolicy -Scope Process Bypass -Force
& C:\Hyper-V\OsTv\setup-ostv-vm.ps1
```

VM створюється і стартує автоматично. Cloud-init (5-15 хв) робить:
- Створює юзера `tv` з паролем `ostv` (sudoer)
- Ставить пакети, тягне latest OsTv release з GitHub
- Запускає `install.sh` → налаштовує kiosk
- Після ребуту → fullscreen OsTv UI

## Перші кроки після запуску

```powershell
# 1. Знайти IP VM
Get-VMNetworkAdapter -VMName OsTv | Select -ExpandProperty IPAddresses

# 2. SSH у VM (тільки з самого host'а — Default Switch internal NAT)
ssh tv@<vm-ip>
# password: ostv
```

⚠ **Перше що робити після ssh: змінити дефолтний пароль:**
```bash
passwd
```

## Зовнішній доступ до VM (опційно)

Default Switch — internal NAT, видно тільки з host'а. Щоб ssh з мережі —
налаштуй portproxy:

```powershell
netsh interface portproxy add v4tov4 listenport=2222 listenaddress=0.0.0.0 `
    connectport=22 connectaddress=<VM-IP>
New-NetFirewallRule -DisplayName "OsTv VM SSH" -Direction Inbound `
    -LocalPort 2222 -Protocol TCP -Action Allow
```

Тепер з мережі: `ssh tv@<host-ip> -p 2222`.

## Обмеження Hyper-V для OsTv

- Немає GPU acceleration (працює на llvmpipe — ~20 FPS, OK для UI/1080p mpv)
- Default Switch IP не персистентний (DHCP lease ротується при ребуті)
- 4K HEVC не варто — CPU softdec не тягне
