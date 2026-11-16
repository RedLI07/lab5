"""Снимки браузера с фактическим выводом команд и сохраненными свидетельствами."""
from pathlib import Path
from datetime import datetime
import html
import json
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
NOW = datetime.now().astimezone().isoformat(timespec="seconds")

def command(args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return "$ " + " ".join(args) + "\n" + result.stdout + result.stderr + "\nКод возврата: " + str(result.returncode)

def capture(name, title, description, text):
    lines = []
    for line in text.splitlines():
        lines.extend(textwrap.wrap(line, width=105, replace_whitespace=False, drop_whitespace=False) or [""])
    text = "\n".join(lines)
    height = min(1600, max(380, 300 + len(lines)*21))
    page = OUT / (name + ".html")
    page.write_text("""<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;padding:30px;background:#edf1f5;color:#122335;font:17px Arial}
header{border-left:5px solid #2463ad;padding-left:17px}h1{font-size:26px;margin:0 0 10px}
p{margin:6px 0;color:#42566b}pre{background:white;border:1px solid #c7d2df;border-radius:6px;
padding:20px;font:16px/21px Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
</style><header><h1>""" + html.escape(title) + "</h1><p>Практическая работа № 5 · вариант 19 → 9</p><p>" + html.escape(description) + "</p><p>Снимок: " + NOW + "</p></header><pre>" + html.escape(text) + "</pre>")
    result = subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=2", "--window-size=1100,"+str(height),
        "--screenshot="+str(OUT / (name+".png")), page.as_uri()],capture_output=True,text=True,timeout=40)
    if result.returncode:
        raise RuntimeError(result.stderr)
    print(name, "captured", flush=True)

capture("01-platform", "1. Паспорт среды", "Фактическая конфигурация Linux Docker Engine",
    command(["docker", "info", "--format", "OS={{.OperatingSystem}}\\nArchitecture={{.Architecture}}\\nKernel={{.KernelVersion}}\\nCPU={{.NCPU}}\\nRAM(bytes)={{.MemTotal}}"]).replace("\\n", "\n") + "\n" +
    command(["docker", "compose", "--env-file", "env.example", "exec", "-T", "disk", "id"]))
capture("02-release-tests", "2. Выпуск и автоматические тесты", "Текущая ветка, аннотированная метка и повторный запуск тестов",
    command(["git", "branch", "--show-current"]) + "\n" +
    command(["git", "cat-file", "-t", "v1.0.0"]) + "\n" +
    command(["git", "log", "-1", "--format=%h %s", "v1.0.0"]) + "\n" +
    command(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]))
capture("03-backup", "3. Резервная копия и восстановление", "Сравнение файлов в разных каталогах и SHA-256",
    command(["shasum", "-a", "256", "backups/state.json", "restored/state.json"]) + "\n" +
    command(["cmp", "backups/state.json", "restored/state.json"]) + "\n" +
    command(["python3", "-m", "json.tool", "restored/state.json"]))
# Короткий формат ps сохраняет читаемость в документе.
capture("04-deployment", "4. Развернутый сервис", "Состояние контейнера и настроенные ограничения ресурсов",
    command(["docker", "compose", "--env-file", "env.example", "ps", "--format", "{{.Name}} | {{.Status}} | {{.Ports}}"])+"\n"+
    command(["docker", "inspect", "practice5-v19-disk-1", "--format", "Memory={{.HostConfig.Memory}}; MemorySwap={{.HostConfig.MemorySwap}}; NanoCpus={{.HostConfig.NanoCpus}}; User={{.Config.User}}"]))
capture("05-http", "4. Функция приложения и негативная проверка", "Ответы реального сервиса на localhost:8219",
    command(["curl", "-sS", "-i", "http://127.0.0.1:8219/health"])+"\n\n"+
    command(["curl", "-sS", "-i", "http://127.0.0.1:8219/disk"])+"\n\n"+
    command(["curl", "-sS", "-i", "http://127.0.0.1:8219/missing"]))
checks=json.loads((ROOT/"evidence/acceptance.json").read_text())
capture("06-acceptance", "4. Приемочные проверки", "Сохраненный результат сценария scripts/deploy_check.py; evidence/acceptance.json",
    "\n\n".join(("PASS" if x["passed"] else "FAIL")+"  "+x["name"] for x in checks)+"\n\nВсего: "+str(len(checks))+" проверок")
failure=(ROOT/"evidence/failure-state.json").read_text()
capture("07-failure", "5. Зафиксированный отказ при 6 MiB", "Состояние из выполненного эксперимента; evidence/failure-state.json",
    "$ cat evidence/failure-state.json\n"+failure)
events=[json.loads(line) for line in (ROOT/"evidence/deployment.jsonl").read_text().splitlines()]
selected=[e for e in events if e["kind"]=="check" and any(s in e["name"] for s in ["Отказ", "Откат", "Данные после отказа", "Итоговый"])]
recovery="\n\n".join(e["time"]+"\n"+e["name"]+": "+("PASS" if e["passed"] else "FAIL") for e in selected)
capture("08-recovery", "5. Откат и текущее состояние", "Журнал восстановления и новый снимок использования ресурсов",
    recovery+"\n\n"+command(["docker", "stats", "--no-stream", "--format", "{{.Name}} | CPU {{.CPUPerc}} | RAM {{.MemUsage}} | PIDs {{.PIDs}}", "practice5-v19-disk-1"])+"\n"+
    command(["docker", "inspect", "practice5-v19-disk-1", "--format", "Health={{.State.Health.Status}}; Memory={{.HostConfig.Memory}}"])+"\n"+
    command(["docker", "compose", "--env-file", "env.example", "logs", "--tail", "5", "--no-color", "disk"]))
