"""Воспроизводимая приемка и учебный отказ. Запускать из lab5."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)
JOURNAL = EVIDENCE / "deployment.jsonl"
COMPOSE = ["docker", "compose", "--env-file", "env.example"]
URL = "http://127.0.0.1:8219"
checks = []


def record(kind, **details):
    event = dict(time=datetime.now(timezone.utc).isoformat(), kind=kind, **details)
    with JOURNAL.open("a") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def run(args, memory="128m", required=True, binary=False):
    result = subprocess.run(args, env=dict(os.environ, MEMORY_LIMIT=memory),
                            capture_output=True, text=not binary)
    if binary:
        record("command", command=args, returncode=result.returncode,
               bytes=len(result.stdout), stderr=result.stderr.decode(errors="replace"))
    else:
        record("command", command=args, memory=memory, returncode=result.returncode,
               stdout=result.stdout, stderr=result.stderr)
    if required and result.returncode:
        raise RuntimeError(f"Command failed: {args}: {result.stderr}")
    return result.stdout


def check(name, condition, **details):
    item = dict(name=name, passed=bool(condition), **details)
    checks.append(item)
    record("check", **item)
    if not condition:
        raise AssertionError(name)


def request(path):
    try:
        with urlopen(URL + path, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def container():
    return run(COMPOSE + ["ps", "-a", "-q", "disk"]).strip()


def inspect():
    return json.loads(run(["docker", "inspect", container()]))[0]


def healthy():
    for _ in range(45):
        status = inspect()["State"]
        if status.get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(1)
    raise RuntimeError("Container failed to become healthy")


def deploy(memory="128m"):
    run(COMPOSE + ["up", "-d", "--no-build", "--force-recreate", "--wait", "--wait-timeout", "60"], memory)
    healthy()


def main():
    record("begin", variant=9, requested_variant=19)
    run(["docker", "version"])
    run(["docker", "info", "--format", "{{json .}}"])
    run(COMPOSE + ["ps", "-a"])
    run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])
    run(COMPOSE + ["config"])
    run(COMPOSE + ["build"])
    image = json.loads(run(["docker", "image", "inspect", "local/practice5-disk:v1.0.0"]))[0]
    (EVIDENCE / "image.json").write_text(json.dumps({k: image[k] for k in ("Id", "RepoTags", "Architecture", "Os", "Created")}, indent=2))

    # Исходная работоспособная конфигурация для проверки отката лимита.
    deploy("96m")
    before = request("/disk")[1]["requests"]
    deploy()
    state = inspect()
    check("Лимиты памяти, swap и CPU", state["HostConfig"]["Memory"] == 128*1024**2
          and state["HostConfig"]["MemorySwap"] == 128*1024**2
          and state["HostConfig"]["NanoCpus"] == 500000000)
    check("Health и версия", request("/health") == (200, {"status": "ok", "version": "v1.0.0"}))
    code, body = request("/disk")
    check("Основная функция под лимитом", code == 200 and body["total_gb"] > 0
          and 0 <= body["free_gb"] <= body["total_gb"] and body["requests"] > before, response=body)
    check("Негативный маршрут", request("/missing")[0] == 404)
    check("Непривилегированный процесс", run(COMPOSE + ["exec", "-T", "disk", "id", "-u"]).strip() == "10019")
    (EVIDENCE / "stats-before.txt").write_text(run(["docker", "stats", "--no-stream", container()]))

    # Согласованная копия: приложение остановлено, том подключается helper-контейнеру только для чтения.
    run(COMPOSE + ["stop", "disk"])
    volume = next(m["Name"] for m in inspect()["Mounts"] if m["Destination"] == "/data")
    backup = run(["docker", "run", "--rm", "--network", "none", "--read-only",
                  "--memory", "128m", "--cpus", "0.5", "-v", volume+":/data:ro",
                  "local/practice5-disk:v1.0.0", "python", "-c",
                  "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path('/data/state.json').read_bytes())"], binary=True)
    Path("backups").mkdir(exist_ok=True)
    Path("restored").mkdir(exist_ok=True)
    Path("backups/state.json").write_bytes(backup)
    Path("restored/state.json").write_bytes(Path("backups/state.json").read_bytes())
    check("Восстановление в отдельный каталог", Path("restored/state.json").read_bytes() == backup
          and isinstance(json.loads(backup)["requests"], int), sha256=hashlib.sha256(backup).hexdigest())
    run(COMPOSE + ["start", "disk"])
    healthy()
    check("Данные после перезапуска", request("/disk")[1]["requests"] == json.loads(backup)["requests"]+1)

    # Одинаковый образ и том, меняется только лимит памяти и политика перезапуска.
    try:
        run(COMPOSE + ["-f", "compose.yaml", "-f", "compose.failure.yaml", "up", "-d", "--no-build", "--force-recreate"])
        for _ in range(30):
            failed = inspect()
            if not failed["State"]["Running"]:
                break
            time.sleep(1)
        (EVIDENCE / "failure-state.json").write_text(json.dumps(failed["State"], indent=2))
        (EVIDENCE / "failure-logs.txt").write_text(run(COMPOSE + ["logs", "--no-color", "--tail", "100", "disk"]))
        check("Отказ при 6 MiB обнаружен", not failed["State"]["Running"]
              and failed["HostConfig"]["Memory"] == 6*1024**2, state=failed["State"])
    finally:
        # Возврат предыдущего проверенного лимита даже при неудаче эксперимента.
        deploy("96m")
    state = inspect()
    check("Откат к предыдущему лимиту 96 MiB", state["HostConfig"]["Memory"] == 96*1024**2
          and request("/health")[0] == 200)
    check("Данные после отказа", request("/disk")[1]["requests"] == json.loads(backup)["requests"]+2)
    deploy()
    check("Итоговый запуск 128 MiB healthy", inspect()["HostConfig"]["Memory"] == 128*1024**2
          and request("/health")[0] == 200)
    (EVIDENCE / "stats-after.txt").write_text(run(["docker", "stats", "--no-stream", container()]))
    (EVIDENCE / "service-logs.txt").write_text(run(COMPOSE + ["logs", "--no-color", "--tail", "100", "disk"]))
    (EVIDENCE / "acceptance.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    record("complete", passed=len(checks))
    print(f"PASS: {len(checks)} acceptance checks; {URL}/disk")


if __name__ == "__main__":
    main()
