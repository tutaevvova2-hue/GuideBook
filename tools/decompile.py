#!/usr/bin/env python3
"""Декомпиляция jar мода в читаемый Java-код, чтобы брать из него числа (урон, прочность, здоровье, выпадение).

Запуск: python3 tools/decompile.py mods/<мод>.jar
Результат: build/src/<имя jar>/ (не попадает в git). Нужны Java 8+ и доступ к интернету (один раз скачивается Vineflower).
Поиск чисел потом обычным grep, например: grep -rn "setMaxDamage\\|ToolMaterial" build/src/<имя>/ | head
"""
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VF = os.path.join(ROOT, "build", "vineflower.jar")
URL = "https://repo1.maven.org/maven2/org/vineflower/vineflower/1.12.0/vineflower-1.12.0.jar"


def main():
    if len(sys.argv) != 2 or not os.path.exists(sys.argv[1]):
        sys.exit(__doc__)
    jar = sys.argv[1]
    if not os.path.exists(VF):
        os.makedirs(os.path.dirname(VF), exist_ok=True)
        print("Скачиваю Vineflower…")
        urllib.request.urlretrieve(URL, VF)
    out = os.path.join(ROOT, "build", "src", os.path.splitext(os.path.basename(jar))[0])
    os.makedirs(out, exist_ok=True)
    print(f"Декомпилирую {jar} -> {out} (может занять несколько минут)")
    subprocess.check_call(["java", "-jar", VF, "-log=WARN", jar, out])
    # Vineflower кладёт результат в jar-подобный архив или в папку, если задана папка
    n = sum(f.endswith(".java") for _, _, fs in os.walk(out) for f in fs)
    print(f"Готово: {n} файлов .java в {out}")


if __name__ == "__main__":
    main()
