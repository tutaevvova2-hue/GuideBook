#!/usr/bin/env python3
"""Справка для автора книги: рецепты и названия предметов IC2.

    python3 tools/show.py te#macerator            рецепты верстака для предмета
    python3 tools/show.py -m macerator oreCopper  рецепты машины, где встречается строка
    python3 tools/show.py -n дробитель            поиск предмета по названию
    python3 tools/show.py -u te#macerator         где предмет используется в рецептах
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tome  # noqa: E402

IC2 = tome.IC2


def name(tok):
    if tok is None:
        return "·"
    it = tome.resolve(tok, "show")
    return f"{it.name} [{tok}]"


def show_recipe(ref):
    r = ref if ref.startswith("ic2:") or ref.startswith("minecraft:") else "ic2:" + ref
    lst = tome.SHAPED.get(r, []) + tome.SHAPELESS.get(r, [])
    if not lst:
        print("нет рецептов верстака для", ref)
    for i, rec in enumerate(lst, 1):
        kind = "без формы" if rec.get("shapeless") else "с формой"
        hid = " (скрытый)" if rec.get("hidden") else ""
        print(f"#{i} {kind}{hid} -> {rec['out']}")
        g = rec["grid"]
        for row in range(3):
            print("   " + " | ".join(name(g[row * 3 + c]) for c in range(3)))


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "-n":
        q = a[1].lower()
        for k, v in IC2["items"].items():
            if q in v["ru"].lower() or q in v["en"].lower() or q in k:
                print(f"{k:50} {v['stack']:40} {v['ru']}")
        return
    if a[0] == "-m":
        mach, q = a[1], (a[2] if len(a) > 2 else "")
        for f, lines in IC2["machines"].items():
            if mach in f:
                for ln in lines:
                    if q in ln:
                        print(f"[{f}] {ln}")
        return
    if a[0] == "-u":
        q = a[1].replace("te#", "ic2:te#")
        for ln in IC2["shaped"] + IC2["shapeless"]:
            left = ln.rsplit(" = ", 1)[0]
            if q in left:
                print(ln)
        for f, lines in IC2["machines"].items():
            for ln in lines:
                if q in ln:
                    print(f"[{f}] {ln}")
        return
    for ref in a:
        show_recipe(ref)


if __name__ == "__main__":
    main()
