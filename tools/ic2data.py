#!/usr/bin/env python3
"""Извлекает из IC2 данные для книг: номера предметов, названия, рецепты.

Использование:
    python3 tools/ic2data.py <ic2.jar> <распакованный декомпилят IC2>

Декомпилят делается CFR: java -jar cfr.jar ic2.jar --outputdir <папка>.
Результат пишется в tools/data/ic2.json. Сами jar-файлы в репозиторий не кладутся.

Что лежит в ic2.json:
  items    — "ic2:te#macerator" -> {"stack": "ic2:te:47", "ru": "Дробитель", "en": "Macerator"}
  shaped   — список рецептов верстака (как в shaped_recipes.ini)
  shapeless
  machines — рецепты машин по файлам *.ini (macerator, compressor, ...)
"""
import json
import os
import re
import sys
import zipfile

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ic2.json")

# Предмет IC2 -> (файл с перечислением, имя перечисления, способ нумерации).
ITEM_TYPES = {
    "crushed": ("item/type/OreResourceType.java", "OreResourceType"),
    "purified": ("item/type/OreResourceType.java", "OreResourceType"),
    "dust": ("item/type/DustResourceType.java", "DustResourceType"),
    "ingot": ("item/type/IngotResourceType.java", "IngotResourceType"),
    "plate": ("item/type/PlateResourceType.java", "PlateResourceType"),
    "casing": ("item/type/CasingResourceType.java", "CasingResourceType"),
    "nuclear": ("item/type/NuclearResourceType.java", "NuclearResourceType"),
    "misc_resource": ("item/type/MiscResourceType.java", "MiscResourceType"),
    "crafting": ("item/type/CraftingItemType.java", "CraftingItemType"),
    "crop_res": ("item/type/CropResItemType.java", "CropResItemType"),
    "block_cutting_blade": ("item/type/BlockCuttingBladeType.java", "BlockCuttingBladeType"),
    "upgrade_kit": ("item/type/UpdateKitType.java", "UpdateKitType"),
    "upgrade": ("item/upgrade/ItemUpgradeModule.java", "UpgradeType"),
    "tfbp": ("item/tfbp/Tfbp.java", "TfbpType"),
    "cover": ("item/logistics/PumpCoverType.java", "PumpCoverType"),
    "mug": ("item/ItemMug.java", "MugType"),
    "boat": ("item/ItemIC2Boat.java", "BoatType"),
    # блоки с вариантами
    "resource": ("block/type/ResourceBlock.java", "ResourceBlock"),
    "fence": ("block/BlockIC2Fence.java", "IC2FenceType"),
    "sheet": ("block/BlockSheet.java", "SheetType"),
    "glass": ("block/BlockTexGlass.java", "GlassType"),
    "foam": ("block/BlockFoam.java", "FoamType"),
    "wall": ("util/Ic2Color.java", "Ic2Color"),
    "scaffold": ("block/BlockScaffold.java", "ScaffoldType"),
    "mining_pipe": ("block/machine/BlockMiningPipe.java", "MiningPipeType"),
}


def enum_constants(src, enum_name):
    """Возвращает [(имя, id)] констант перечисления в порядке объявления."""
    m = re.search(r"enum " + enum_name + r"\b[^{]*\{", src)
    if not m:
        # CFR иногда разворачивает enum в класс: "public static final /* enum */ X a = new X(1);"
        found = re.findall(r"/\* enum \*/ " + enum_name + r" (\w+) = new " + enum_name + r"\((-?\d+)?", src)
        if not found:
            raise ValueError("нет перечисления " + enum_name)
        return [(n, int(i) if i else k) for k, (n, i) in enumerate(found)]
    body = src[m.end():]
    uses_ordinal = None
    consts = []
    # Константы идут до первой ';' на верхнем уровне.
    depth = 0
    i = 0
    start = 0
    items = []
    while i < len(body):
        c = body[i]
        if c in "({":
            depth += 1
        elif c in ")}":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            items.append(body[start:i])
            start = i + 1
        elif c == ";" and depth == 0:
            items.append(body[start:i])
            break
        i += 1
    rest = body[i:]
    gm = re.search(r"public int getId\(\)\s*\{\s*return ([^;]+);", rest)
    uses_ordinal = gm is None or "ordinal" in gm.group(1)
    for n, raw in enumerate(items):
        raw = raw.strip()
        if not raw:
            continue
        cm = re.match(r"(\w+)\s*(?:\((.*)\))?", raw, re.S)
        name, args = cm.group(1), cm.group(2) or ""
        if uses_ordinal:
            consts.append((name, n))
        else:
            im = re.search(r"-?\d+", args)
            consts.append((name, int(im.group(0))))
    return consts


def te_blocks(src):
    res = []
    for m in re.finditer(r"TeBlock (\w+) = new TeBlock\(([^,]+), (-?\d+),", src):
        if int(m.group(3)) >= 0:
            res.append((m.group(1), int(m.group(3))))
    return res


def cable_types(src):
    return enum_constants(src, "CableType")


def load_lang(zf, lang):
    try:
        data = zf.read(f"assets/ic2/lang_ic2/{lang}.properties").decode("utf-8")
    except KeyError:
        return {}
    res = {}
    for line in data.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip()
    return res


def parse_ini(text):
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        lines.append(line)
    return lines


def main(jar, dec):
    core = os.path.join(dec, "ic2", "core")
    zf = zipfile.ZipFile(jar)
    ru = load_lang(zf, "ru_ru")
    en = load_lang(zf, "en_us")

    items = {}

    def add(variant, stack, key):
        items[variant] = {"stack": stack, "ru": ru.get(key) or en.get(key) or "", "en": en.get(key, ""),
                          "key": key}

    # Типизированные предметы и блоки
    for name, (path, enum) in ITEM_TYPES.items():
        with open(os.path.join(core, path), encoding="utf-8") as f:
            src = f.read()
        for tname, tid in enum_constants(src, enum):
            add(f"ic2:{name}#{tname}", f"ic2:{name}:{tid}", f"{name}.{tname}")

    # Машины и прочие блоки с тайлами
    with open(os.path.join(core, "ref", "TeBlock.java"), encoding="utf-8") as f:
        for tname, tid in te_blocks(f.read()):
            add(f"ic2:te#{tname}", f"ic2:te:{tid}", f"te.{tname}")

    # Провода: номер = тип, изоляция и тип хранятся в NBT
    with open(os.path.join(core, "block", "wiring", "CableType.java"), encoding="utf-8") as f:
        for tname, tid in cable_types(f.read()):
            for ins in range(0, 4):
                key = f"cable.{tname}_cable_{ins}"
                if key not in en and key not in ru:
                    # У проводов без изоляции (стекловолокно, детектор) ключ без номера
                    key = f"cable.{tname}_cable"
                    if ins != 0 or (key not in en and key not in ru):
                        continue
                add(f"ic2:cable#type:{tname},insulation:{ins}",
                    f"ic2:cable:{tid}{{type:{tid}b,insulation:{ins}b}}", key)

    # Простые предметы IC2: всё, что есть в ItemName без типов
    with open(os.path.join(core, "ref", "ItemName.java"), encoding="utf-8") as f:
        src = f.read()
    for tname, _ in enum_constants(src, "ItemName"):
        if tname in ITEM_TYPES or tname == "cable":
            continue
        add(f"ic2:{tname}", f"ic2:{tname}", tname)
    with open(os.path.join(core, "ref", "BlockName.java"), encoding="utf-8") as f:
        src = f.read()
    for tname, _ in enum_constants(src, "BlockName"):
        if tname in ITEM_TYPES or tname == "te":
            continue
        add(f"ic2:{tname}", f"ic2:{tname}", tname)

    # Словарь руд IC2: "plateIron" -> ["ic2:plate#iron"]
    oredict = {}
    with open(os.path.join(core, "recipe", "OreDictionaryEntries.java"), encoding="utf-8") as f:
        src = f.read()
    for m in re.finditer(r'OreDictionaryEntries\.add\("(\w+)", (.+?)\);\n', src):
        name, expr = m.group(1), m.group(2)
        v = None
        mm = re.search(r"(ItemName|BlockName)\.(\w+)\.getItemStack\((?:\w+\.(\w+))?\)", expr)
        if mm:
            v = f"ic2:{mm.group(2)}" + (f"#{mm.group(3)}" if mm.group(3) else "")
        mm = re.search(r"ItemCable\.getCable\(CableType\.(\w+), (\d)\)", expr)
        if mm:
            v = f"ic2:cable#type:{mm.group(1)},insulation:{mm.group(2)}"
        if v:
            oredict.setdefault(name, []).append(v)

    # Рецепты
    cfg = {}
    for n in zf.namelist():
        if n.startswith("assets/ic2/config/") and n.endswith(".ini"):
            cfg[os.path.basename(n)[:-4]] = parse_ini(zf.read(n).decode("utf-8"))

    shaped = [{"raw": line} for line in cfg.pop("shaped_recipes")]
    shapeless = [{"raw": line} for line in cfg.pop("shapeless_recipes")]
    machines = {k: v for k, v in cfg.items() if k not in ("general", "uu_scan_values")}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"items": items, "shaped": [r["raw"] for r in shaped],
                   "shapeless": [r["raw"] for r in shapeless], "machines": machines, "oredict": oredict,
                   "lang_ru": ru, "lang_en": en},
                  f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"{OUT}: {len(items)} предметов, {len(shaped)} рецептов верстака, "
          f"{len(shapeless)} бесформенных, машин: {len(machines)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
