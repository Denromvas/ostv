# OsTv Release Distribution

## Що тут
- `ostv-release-v0.1.0.tar.gz` — повний runtime bundle (~2.8 МБ)
- `ostv-ui` — Tauri 2 standalone binary

## Установка на чистій Ubuntu 22.04/24.04 (або Debian 12+)

### Варіант A — один рядок:
```bash
sudo bash install.sh --local ostv-release-v0.1.0.tar.gz
```

### Варіант B — покроково:
```bash
# 1. Скопіюй tarball на цільову машину
scp ostv-release-v0.1.0.tar.gz user@target:/tmp/

# 2. SSH на target
ssh user@target

# 3. Extract + install
cd /tmp
tar -xzf ostv-release-v0.1.0.tar.gz
cd release
sudo bash install.sh --local ../ostv-release-v0.1.0.tar.gz
```

## Post-install

Вставити Claude API key або залогінитись через OAuth:
```bash
# Варіант 1: API key
echo 'ANTHROPIC_API_KEY=sk-ant-...' | sudo tee -a /etc/ostv/secrets.env

# Варіант 2: OAuth (рекомендовано, безкоштовно для Claude.ai account)
sudo -u tv bash -c 'claude'  # → /login → follow instructions
```

Перезавантажити:
```bash
sudo reboot
```

## Опції installer

- `--skip-kiosk` — не переводити на kiosk autostart (для розробки поверх GDM)
- `--rollback` — повернути GDM+GNOME

## Rebuild зі свіжих source

```bash
# На dev-машині
bash scripts/build-release.sh 0.1.1
```

Це автоматично:
1. Копіює Brain + parsers з `/mnt/e/OsTv/src/`
2. Pull-ить Tauri binary з `$TARGET_HOST` (передавати env-змінною)
3. Пакує все в `ostv-release-v<ver>.tar.gz`
