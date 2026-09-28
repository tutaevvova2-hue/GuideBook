#!/usr/bin/env python3
"""Выгрузка из jar мода (без кода): русские названия предметов и рецепты верстака из JSON.

Запуск: python3 tools/moddata.py <mod.jar> <modid>  ->  tools/data/mod_<modid>.json
Формат: {"items": {"modid:name": {"ru", "stack"}}, "recipes": {"modid:name": [{"grid": [9], "out", "shapeless"}]}}
Ингредиенты: "ore:X", "modid:name" или "modid:name:meta", варианты через «|».
"""
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main(jar, modid):
    z = zipfile.ZipFile(jar)
    names = {n: n for n in z.namelist()}
    lang = {}
    for n in names:
        if n.lower() == f"assets/{modid}/lang/ru_ru.lang":
            for ln in z.read(n).decode("utf-8").splitlines():
                if "=" in ln and not ln.startswith("#"):
                    k, v = ln.split("=", 1)
                    lang[k.strip()] = v.strip()
    items = {}
    for k, v in lang.items():
        for pre in ("item.", "tile."):
            if k.startswith(pre) and k.endswith(".name"):
                reg = f"{modid}:{k[len(pre):-5]}"
                items.setdefault(reg, {"ru": v, "stack": reg})
    rdir = f"assets/{modid}/recipes/"
    consts = {}
    if rdir + "_constants.json" in names:
        for c in json.loads(z.read(rdir + "_constants.json")):
            consts["#" + c["name"]] = c["ingredient"]

    def ing(x):
        if isinstance(x, list):
            return "|".join(ing(i) for i in x)
        if "item" in x and x["item"].startswith("#"):
            return ing(consts[x["item"]])
        if x.get("type") == "forge:ore_dict":
            return "ore:" + x["ore"]
        s = x["item"]
        if "data" in x and x["data"] not in (0, 32767):
            s += f":{x['data']}"
        return s

    def out(r):
        o = r["result"]
        s = o["item"] + (f":{o['data']}" if o.get("data") else "")
        return s + (f"*{o['count']}" if o.get("count", 1) > 1 else "")

    recipes = {}
    for n in sorted(names):
        if not n.startswith(rdir) or not n.endswith(".json") or "/_" in n:
            continue
        r = json.loads(z.read(n))
        t = r.get("type", "")
        if t.endswith("shaped"):
            pat = r["pattern"]
            grid = []
            for row in range(3):
                line = pat[row] if row < len(pat) else ""
                for col in range(3):
                    ch = line[col] if col < len(line) else " "
                    grid.append(ing(r["key"][ch]) if ch != " " else None)
            rec = {"grid": grid, "out": out(r)}
        elif t.endswith("shapeless"):
            ins = [ing(i) for i in r["ingredients"]]
            rec = {"grid": ins + [None] * (9 - len(ins)), "out": out(r), "shapeless": True}
        else:
            continue
        recipes.setdefault(rec["out"].split("*")[0], []).append(rec)
    path = os.path.join(HERE, "data", f"mod_{modid}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"items": items, "recipes": recipes}, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(path, len(items), "предметов,", sum(map(len, recipes.values())), "рецептов")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
