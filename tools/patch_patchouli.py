#!/usr/bin/env python3
"""Собирает изменённый Patchouli: берёт vendor/Patchouli-1.0-23.6-nobuttons.jar
(там уже правки классов: одна кнопка «История», скрытые статьи в шкале считаются вместе с обычными)
и подменяет файлы из vendor/patchouli-overrides:
- русские подписи шкалы прогресса;
- BookTextParser.class: ссылка на закрытую статью не открывает её (см. tools/patches/LockedLinkPatch.java).

Результат: dist/Patchouli-1.0-23.6-tomes.jar
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "vendor", "Patchouli-1.0-23.6-nobuttons.jar")
OVR = os.path.join(ROOT, "vendor", "patchouli-overrides")
OUT = os.path.join(ROOT, "dist", "Patchouli-1.0-23.6-tomes.jar")


def main():
    overrides = {}
    for dirpath, _, files in os.walk(OVR):
        for name in files:
            path = os.path.join(dirpath, name)
            overrides[os.path.relpath(path, OVR).replace(os.sep, "/")] = path
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename in overrides:
                with open(overrides.pop(info.filename), "rb") as f:
                    dst.writestr(info, f.read())
            else:
                dst.writestr(info, src.read(info.filename))
        for arc, path in overrides.items():
            with open(path, "rb") as f:
                dst.writestr(arc, f.read())
    print(OUT)


if __name__ == "__main__":
    main()
