#!/usr/bin/env python3
"""Сборка мода Tomes в jar.

Использование:
    python3 build.py            # собрать dist/Tomes-1.12.2-<версия>.jar
    python3 build.py --check    # только проверить JSON и ссылки, без сборки

Версия берётся из tomes/resources/mcmod.info.
"""
import json
import os
import re
import shutil
import subprocess
import sys

try:  # консоль Windows: русский текст без ошибок кодировки
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(ROOT, "tomes")
RES = os.path.join(MOD, "resources")
BUILD = os.path.join(ROOT, "build")
GEN = os.path.join(BUILD, "gen")
DIST = os.path.join(ROOT, "dist")

# Фиксированное время в zip, чтобы одинаковые исходники давали одинаковый jar.
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def version():
    with open(os.path.join(RES, "mcmod.info"), encoding="utf-8") as f:
        return json.load(f)[0]["version"]


def generate():
    """Собирает книги из разметки books/ в build/gen (см. tools/tome.py)."""
    shutil.rmtree(GEN, ignore_errors=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "tome.py"), GEN])
    if r.returncode:
        sys.exit(r.returncode)


def roots():
    return [RES, GEN]


def check():
    """Проверяет, что все JSON читаются, а ссылки внутри книг ведут на существующие статьи."""
    errors = []
    for dirpath, _, files in [w for r in roots() for w in os.walk(r)]:
        for name in files:
            if name.endswith((".json", ".mcmeta", ".info")):
                path = os.path.join(dirpath, name)
                try:
                    with open(path, encoding="utf-8") as f:
                        json.load(f)
                except ValueError as e:
                    errors.append(f"{os.path.relpath(path, ROOT)}: {e}")

    books = os.path.join(GEN, "assets", "tomes", "patchouli_books")
    adv_root = os.path.join(GEN, "assets", "tomes", "advancements")
    for book in sorted(os.listdir(books)):
        for lang in sorted(os.listdir(os.path.join(books, book))):
            base = os.path.join(books, book, lang)
            if not os.path.isdir(base):
                continue
            ent_dir = os.path.join(base, "entries")
            cat_dir = os.path.join(base, "categories")
            entries = set()
            for dirpath, _, files in os.walk(ent_dir):
                for name in files:
                    rel = os.path.relpath(os.path.join(dirpath, name), ent_dir)
                    entries.add(rel[:-5].replace(os.sep, "/"))
            cats = {n[:-5] for n in os.listdir(cat_dir)} if os.path.isdir(cat_dir) else set()
            for e in sorted(entries):
                path = os.path.join(ent_dir, e + ".json")
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                data = json.loads(text)
                where = f"{book}/{lang}/{e}"
                if data.get("category") not in cats:
                    errors.append(f"{where}: нет раздела {data.get('category')}")
                for link in re.findall(r"\$\(l:([^)#]+)", text):
                    if link not in entries:
                        errors.append(f"{where}: ссылка на несуществующую статью {link}")
                adv = data.get("advancement")
                if adv:
                    ns, p = adv.split(":", 1)
                    if ns == "tomes" and not os.path.exists(os.path.join(adv_root, p + ".json")):
                        errors.append(f"{where}: нет достижения {adv}")
                for i, page in enumerate(data.get("pages", [])):
                    t = page.get("type", "")
                    if t.startswith("tomes:"):
                        tpl = os.path.join(base, "templates", t.split(":", 1)[1] + ".json")
                        if not os.path.exists(tpl):
                            errors.append(f"{where} стр.{i + 1}: нет шаблона {t}")
                    for img in page.get("images", []):
                        ns, p = img.split(":", 1)
                        if ns == "tomes" and not any(os.path.exists(os.path.join(r, "assets", "tomes", p)) for r in roots()):
                            errors.append(f"{where} стр.{i + 1}: нет картинки {img}")
    return errors


def compile_class():
    out = os.path.join(BUILD, "classes")
    stubs = os.path.join(BUILD, "stubs")
    src = os.path.join(BUILD, "src", "tomes")
    for d in (out, stubs, src):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    with open(os.path.join(MOD, "java", "tomes", "Tomes.java"), encoding="utf-8") as f:
        code = f.read().replace("@VERSION@", version())
    with open(os.path.join(src, "Tomes.java"), "w", encoding="utf-8") as f:
        f.write(code)
    stub_src = os.path.join(MOD, "stubs", "net", "minecraftforge", "fml", "common", "Mod.java")
    subprocess.run(["javac", "--release", "8", "-nowarn", "-d", stubs, stub_src], check=True)
    subprocess.run(["javac", "--release", "8", "-nowarn", "-encoding", "UTF-8", "-cp", stubs, "-d", out,
                    os.path.join(src, "Tomes.java")], check=True)
    return os.path.join(out, "tomes", "Tomes.class")


def build():
    generate()
    errors = check()
    if errors:
        print("Ошибки:\n  " + "\n  ".join(errors))
        sys.exit(1)
    cls = compile_class()
    os.makedirs(DIST, exist_ok=True)
    jar = os.path.join(DIST, f"Tomes-1.12.2-{version()}.jar")

    def add(z, arcname, data):
        info = zipfile.ZipInfo(arcname, ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, data)

    with zipfile.ZipFile(jar, "w") as z:
        add(z, "META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\r\n\r\n")
        with open(cls, "rb") as f:
            add(z, "tomes/Tomes.class", f.read())
        seen = set()
        for root in roots():
            for dirpath, dirs, files in os.walk(root):
                dirs.sort()
                for name in sorted(files):
                    path = os.path.join(dirpath, name)
                    arc = os.path.relpath(path, root).replace(os.sep, "/")
                    if arc in seen:
                        print(f"Ошибка: {arc} есть и в tomes/resources, и в сгенерированном")
                        sys.exit(1)
                    seen.add(arc)
                    with open(path, "rb") as f:
                        add(z, arc, f.read())
    print(jar)


if __name__ == "__main__":
    if "--check" in sys.argv:
        generate()
        errs = check()
        print("\n".join(errs) if errs else "OK")
        sys.exit(1 if errs else 0)
    build()
