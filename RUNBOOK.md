# Runbook: disk-service v1.0.0

## Предусловия и остановка процедуры

Работать из `lab5`. Нужны доступный Linux Docker Engine (на этой машине Linux VM
Docker Desktop), Compose, Python и свободный localhost:8219. Использовать только
проект `practice5-v19`; согласование приложения с преподавателем выполняется студентом.
Для штатного запуска: 128 MiB без swap, 0.5 CPU; ранее проверенный лимит: 96 MiB.
Образ один и тот же: `local/practice5-disk:v1.0.0`.

Остановить продвижение при ошибке тестов, сборки, резервирования, несовпадении SHA-256,
недоступности `/disk` или отсутствии healthy за 60 секунд. Не удалять том.
При ошибке приемки вернуть предыдущую конфигурацию, проверить health и счетчик.

## Контрольные точки развертывания

1. Зафиксировать время, исходное состояние и версию:

```sh
date -u
git status --short
git branch --show-current
git describe --tags --always
docker version
docker compose --env-file env.example ps -a
python3 -m unittest discover -s tests -v
docker compose --env-file env.example config
docker compose --env-file env.example build
docker image inspect local/practice5-disk:v1.0.0
```

2. Резервирование перед заменой: сначала `docker compose stop disk`.
Сценарий `scripts/deploy_check.py` получает точное имя тома из inspect,
подключает его к временному контейнеру только для чтения, выгружает `state.json`
в `backups/state.json`, копирует его в отдельный каталог `restored` и сравнивает
байты, SHA-256 и структуру JSON. Копия предназначена для учебной проверки;
для эксплуатации нужна дополнительная копия вне этого компьютера.

3. Запуск и контроль:

```sh
docker compose --env-file env.example up -d --no-build --force-recreate --wait --wait-timeout 60
curl --fail http://127.0.0.1:8219/health
curl --fail http://127.0.0.1:8219/disk
docker compose --env-file env.example exec -T disk id -u
docker compose --env-file env.example stats --no-stream
docker compose --env-file env.example logs --tail 100
```

Ожидаются healthy, версия v1.0.0, UID 10019, положительная емкость,
сохраненный счетчик и лимит 128 MiB. `/missing` должен вернуть HTTP 404.
Перезапустить контейнер и проверить рост счетчика на единицу при следующем `/disk`.
Автоматический сценарий выполняет эти проверки и создает журнал с кодами возврата.

## Отказ и откат лимита (задания 3 и 5)

Предыдущая конфигурация устанавливается и проверяется перед продвижением:

```sh
MEMORY_LIMIT=96m docker compose --env-file env.example up -d --force-recreate --wait
MEMORY_LIMIT=128m docker compose --env-file env.example up -d --force-recreate --wait
```

Безопасный эксперимент выполняется в собственном проекте. Снизить память до 6 MiB;
в override отключен restart, память+swap также 6 MiB:

```sh
docker compose --env-file env.example -f compose.yaml -f compose.failure.yaml up -d --no-build --force-recreate
docker compose --env-file env.example ps -a
docker inspect practice5-v19-disk-1 --format '{{json .State}}'
docker compose --env-file env.example logs --tail 100
```

Зафиксировать состояние exited, код завершения, OOMKilled и ошибки Python.
Наличие OOMKilled не обязательно: Python может завершиться с ошибкой выделения памяти.
Критерий отказа: тот же сервис не запускается при 6 MiB, health недоступен.
Вернуть предыдущую работоспособную конфигурацию **без failure override**:

```sh
MEMORY_LIMIT=96m docker compose --env-file env.example up -d --no-build --force-recreate --wait --wait-timeout 60
curl --fail http://127.0.0.1:8219/health
curl --fail http://127.0.0.1:8219/disk
```

Подтвердить 96 MiB через inspect и сохранность счетчика. Затем вернуть штатные 128 MiB:

```sh
MEMORY_LIMIT=128m docker compose --env-file env.example up -d --no-build --force-recreate --wait
```

Сценарий использует `finally`, чтобы возврат 96 MiB выполнялся и при ошибке эксперимента.
Не запускать всеобщее удаление контейнеров, образов или томов.

## Разделение компонентов и наблюдение

Код находится в образе `/app/main.py` (файловая система read-only), настройки — в Compose
и локальном `.env`, данные — `/data/state.json`, журналы — stdout/stderr Docker
с ротацией 2 × 5 MiB. Секретов у приложения нет; `.env` не хранится в Git.
Healthcheck каждые 5 секунд проверяет HTTP и чтение состояния; ошибка помечает
контейнер unhealthy. Политика unless-stopped восстанавливает завершившийся процесс,
но не перезапускает контейнер только по unhealthy. Диагностика: ps, inspect, logs, stats.
При устойчивом unhealthy оператор выясняет причину и восстанавливает данные/настройки.

Источники: [ограничения ресурсов](https://docs.docker.com/engine/containers/resource_constraints/),
[Compose services](https://docs.docker.com/reference/compose-file/services/).
