#!/usr/bin/env python3
"""Компилятор книг Tomes: разметка books/<книга>/*.txt -> JSON для Patchouli.

Что делает:
  * собирает разделы и статьи из текстовой разметки (формат описан в books/FORMAT.md);
  * подставляет рецепты верстака и машин прямо из данных IC2 (tools/data/ic2.json);
  * создаёт скрытые достижения для постепенного открытия статей;
  * дописывает в конец статей страницу «Что дальше»;
  * проверяет ссылки, предметы и то, что текст помещается на страницу
    (ширины символов — из шрифта Minecraft 1.12.2, перенос строк — как в Patchouli).

Запуск: python3 tools/tome.py <папка вывода>   (обычно его вызывает build.py)
"""
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOOKS = os.path.join(ROOT, "books")
DATA = os.path.join(HERE, "data")
MODID = "tomes"

# ---------------------------------------------------------------- данные


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


IC2 = load_json(os.path.join(DATA, "ic2.json"))
EXTRA = load_json(os.path.join(DATA, "items_extra.json"))  # ванильные и прочие предметы
GLYPHS = open(os.path.join(DATA, "glyph_sizes.bin"), "rb").read()


class BuildError(Exception):
    pass


ERRORS = []
WARNINGS = []


def err(where, msg):
    ERRORS.append(f"{where}: {msg}")


def warn(where, msg):
    WARNINGS.append(f"{where}: {msg}")


# ---------------------------------------------------------------- шрифт

def char_width(c):
    """Ширина символа в юникод-шрифте Minecraft 1.12.2 (Patchouli рисует им текст книг)."""
    o = ord(c)
    if o == 160 or c == " ":
        return 4
    if o == 167:
        return -1
    if o >= len(GLYPHS) or GLYPHS[o] == 0:
        return 0
    j = GLYPHS[o]
    k = j >> 4
    lo = (j & 15) + 1
    return (lo - k) // 2 + 1


def str_width(s, bold=False):
    w = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == "§" and i + 1 < len(s):
            i += 2
            continue
        cw = char_width(c)
        if cw > 0:
            w += cw + (1 if bold else 0)
        i += 1
    return w


def layout_lines(text, width=116):
    """Грубая, но близкая к Patchouli раскладка: возвращает число строк (с учётом пустых)."""
    # Разбиваем на абзацы по командам переноса, считаем переносы строк
    tokens = re.split(r"(\$\([^)]*\))", text)
    lines = 1
    x = 0
    bold = False
    pending_word = ""
    words = []  # (ширина слова, пробел после)

    def flush_word():
        nonlocal x, lines, pending_word
        if not pending_word:
            return
        w = str_width(pending_word, bold)
        if x > 0 and x + w > width:
            lines += 1
            x = 0
        while w > width:  # очень длинное слово режется посередине
            lines += 1
            w -= width
        x += w
        pending_word = ""

    for tok in tokens:
        if tok.startswith("$(") and tok.endswith(")"):
            cmd = tok[2:-1]
            if cmd in ("br",):
                flush_word()
                lines += 1
                x = 0
            elif cmd in ("br2", "2br", "p"):
                flush_word()
                lines += 2
                x = 0
            elif re.fullmatch(r"li\d?", cmd):
                flush_word()
                lines += 1
                dist = int(cmd[2]) if len(cmd) > 2 else 1
                x = dist * 4 + str_width("•") + 4
            elif cmd in ("l", "bold"):
                bold = True
            elif cmd in ("", "reset", "clear"):
                bold = False
            elif cmd.startswith("k:"):
                pending_word += "Shift"
            continue
        for ch in tok:
            if ch == " ":
                flush_word()
                if x > 0:
                    x += 4
                    if x > width:
                        x = width
            else:
                pending_word += ch
    flush_word()
    return lines


def text_bottom(text, start_y, width=116):
    return start_y + (layout_lines(text, width) - 1) * 9


PAGE_BOTTOM = 141  # верх последней строки не ниже этого: сверено со скриншотом страницы в игре


# ---------------------------------------------------------------- предметы

class Item:
    def __init__(self, ref, stack, name, trigger):
        self.ref = ref
        self.stack = stack  # строка Patchouli: "ic2:te:47", "minecraft:iron_ingot" или список через запятую
        self.name = name
        self.trigger = trigger  # условие для достижения


VANILLA_ORE = EXTRA["oredict"]


def resolve(ref, where="?", count=1):
    """Ссылка на предмет -> Item. Поддерживаются:
    ic2:te#macerator, te#macerator (без ic2:), ic2:treetap, minecraft:iron_ingot[@meta],
    ore:plateIron / OreDict:plateIron, fluid:water, а также готовая строка Patchouli (ic2:te:47).
    """
    ref = ref.strip()
    amount = count
    m = re.match(r"^(.*)\*(\d+)$", ref)
    if m and not ref.startswith("{"):
        ref, amount = m.group(1), int(m.group(2))
    suffix = f"#{amount}" if amount > 1 else ""
    if "|" in ref:
        # Несколько вариантов: «OreDict:dustTin|ic2:crushed#tin». Имя и условие — по первому.
        parts = [resolve(p, where, amount) for p in ref.split("|")]
        return Item(ref, ",".join(p.stack for p in parts), parts[0].name, parts[0].trigger)
    if ref.startswith("OreDict:"):
        ref = "ore:" + ref[8:]
    if ref.startswith("Fluid:"):
        ref = "fluid:" + ref[6:]
    if ref.startswith("ic2:fluid_cell#"):
        fl = ref.split("#", 1)[1]
        stack = 'ic2:fluid_cell' + suffix + '{Fluid:{FluidName:"%s",Amount:1000}}' % fl
        return Item(ref, stack, EXTRA["fluid_cell_names"].get(fl, "Капсула: " + fl), {"item": "ic2:fluid_cell"})
    if ref.startswith("ore:"):
        name = ref[4:].split("@")[0]
        stacks = []
        variants = IC2["oredict"].get(name, [])
        for v in variants:
            stacks.append(IC2["items"][v]["stack"])
        for s in VANILLA_ORE.get(name, []):
            stacks.append(s)
        if not stacks:
            err(where, f"словарь руд {name}: не знаю ни одного предмета")
            stacks = [ref]
        nm = EXTRA["ore_names"].get(name)
        if nm is None and variants:
            nm = IC2["items"][variants[0]]["ru"]
        if nm is None and VANILLA_ORE.get(name):
            nm = vanilla_name(VANILLA_ORE[name][0])
        trig = {"type": "forge:ore_dict", "ore": name}
        # Количество дописываем к каждому варианту, иначе Patchouli покажет его только у последнего
        return Item(ref, ",".join(s + suffix for s in stacks), nm or name, trig)
    if ref.startswith("fluid:"):
        fl = ref[6:]
        st = EXTRA["fluids"].get(fl)
        if not st:
            err(where, f"жидкость {fl}: не знаю, чем её показать")
            st = ["minecraft:bucket"]
        return Item(ref, ",".join(st), EXTRA["fluid_names"].get(fl, fl), None)
    if ref.startswith("te#") or (("#" in ref) and ":" not in ref.split("#")[0]):
        ref = "ic2:" + ref
    meta_any = False
    if "@" in ref:
        ref, meta = ref.split("@", 1)
        if meta == "*":
            meta_any = True
        elif ref.startswith("minecraft:"):
            ref = f"{ref}:{meta}"
    if ref in IC2["items"]:
        d = IC2["items"][ref]
        stack = d["stack"]
        # ic2:te:47 -> item ic2:te, data 47; провода — любой провод этого типа
        parts = stack.split("{")[0].split(":")
        trig = {"item": f"{parts[0]}:{parts[1]}"}
        if len(parts) > 2 and not meta_any and not stack.startswith("ic2:cable"):
            trig["data"] = int(parts[2])
        if "{" in stack:
            # count ставится до NBT: ic2:cable:0#3{...}
            base, nbt = stack.split("{", 1)
            return Item(ref, base + suffix + "{" + nbt, d["ru"], trig)
        return Item(ref, stack + suffix, d["ru"], trig)
    if ref in EXTRA["items"]:
        d = EXTRA["items"][ref]
        return Item(ref, d["stack"] + suffix, d["ru"], d.get("trigger") or trigger_for(d["stack"]))
    if re.match(r"^[a-z0-9_]+:[a-z0-9_]+(:\d+)?(\{.*\})?$", ref):
        name = vanilla_name(ref)
        if name is None:
            warn(where, f"нет названия для {ref}")
        return Item(ref, ref + suffix, name or ref, trigger_for(ref))
    err(where, f"не понимаю предмет «{ref}»")
    return Item(ref, "minecraft:barrier", ref, None)


def stack_keys(it):
    """Набор «предмет:мета» без количества и NBT — чтобы сравнивать ore:oreTin и ic2:resource#tin_ore."""
    keys = set()
    for st in it.stack.split(","):
        base = st.split("{")[0].split("#")[0]
        if base.count(":") == 1:
            base += ":0"
        keys.add(base)
    return keys


def trigger_for(stack):
    parts = stack.split("{")[0].split(":")
    t = {"item": f"{parts[0]}:{parts[1]}"}
    if len(parts) > 2:
        t["data"] = int(parts[2])
    return t


def vanilla_name(stack):
    key = stack.split("{")[0]
    if key in EXTRA["items"]:
        return EXTRA["items"][key]["ru"]
    if key.count(":") == 1 and key + ":0" in EXTRA["items"]:
        return EXTRA["items"][key + ":0"]["ru"]
    return None


# ---------------------------------------------------------------- рецепты IC2

def parse_ingredient(tok):
    """Вход из ini IC2: 'OreDict:plankWood', 'ic2:crafting#circuit', 'a|b', 'minecraft:stone@*'."""
    return tok


def shaped_recipes():
    res = {}
    for line in IC2["shaped"]:
        left, out = line.rsplit(" = ", 1)
        out = out.split(" @")[0].strip()
        m = re.match(r'"([^"]*)"\s*(.*)$', left)
        if not m:
            continue
        pattern, rest = m.group(1), m.group(2)
        keys = {}
        for tok in re.findall(r"(\S):(\S+)", rest):
            keys[tok[0]] = tok[1]
        rows = pattern.split("|")
        grid = []
        for r in range(3):
            row = rows[r] if r < len(rows) else ""
            for c in range(3):
                ch = row[c] if c < len(row) else " "
                grid.append(keys.get(ch) if ch != " " else None)
        base = out.split("*")[0]
        res.setdefault(base, []).append({"grid": grid, "out": out, "hidden": "@hidden" in left})
    return res


def shapeless_recipes():
    res = {}
    for line in IC2["shapeless"]:
        left, out = line.rsplit(" = ", 1)
        out = out.split(" @")[0].strip()
        ins = [t for t in left.split() if not t.startswith("@")]
        base = out.split("*")[0]
        grid = ins + [None] * (9 - len(ins))
        res.setdefault(base, []).append({"grid": grid, "out": out, "shapeless": True})
    return res


SHAPED = shaped_recipes()
SHAPELESS = shapeless_recipes()


def find_recipe(out_ref, index, where):
    ref = out_ref
    if ref.startswith("te#") or ("#" in ref and ":" not in ref.split("#")[0]):
        ref = "ic2:" + ref
    lst = SHAPED.get(ref, []) + SHAPELESS.get(ref, [])
    lst = [r for r in lst if not r.get("hidden")] or lst
    if not lst:
        err(where, f"нет рецепта верстака для {out_ref}")
        return None
    if index > len(lst):
        err(where, f"у {out_ref} только {len(lst)} рецепт(а), а запрошен {index}-й")
        return None
    return lst[index - 1]


MACHINE_INI = {
    "ic2:te#macerator": ["macerator"],
    "ic2:te#extractor": ["extractor"],
    "ic2:te#compressor": ["compressor"],
    "ic2:te#electric_furnace": ["furnace"],
    "ic2:te#iron_furnace": ["furnace"],
    "ic2:te#induction_furnace": ["furnace"],
    "ic2:te#metal_former": ["metal_former_rolling", "metal_former_cutting", "metal_former_extruding"],
    "ic2:te#ore_washing_plant": ["ore_washer"],
    "ic2:te#centrifuge": ["thermal_centrifuge"],
    "ic2:te#blast_furnace": ["blast_furnace"],
    "ic2:te#block_cutter": ["block_cutter", "block_cutter_late"],
}


def machine_recipe_exists(machine, inp, outs):
    """Проверка, что строка «вход -> выход» действительно есть в рецептах машины."""
    files = MACHINE_INI.get(machine)
    if not files:
        return None  # машина без ini — проверить нечем
    norm = lambda s: s.replace("OreDict:", "ore:").replace("ic2:", "")
    want_in = norm(inp)
    want_out = [norm(o) for o in outs]
    for f in files:
        for line in IC2["machines"].get(f, []):
            left, right = line.split(" = ", 1)
            outs_l = [t for t in right.split() if not t.startswith("@")]
            if norm(left.strip()) == want_in and [norm(o) for o in outs_l] == want_out:
                return True
    return False


# ---------------------------------------------------------------- разметка текста

def markup(text, ctx):
    """Упрощённая разметка -> коды Patchouli.

    Пустая строка -> новый абзац; строка «- ...» -> пункт списка;
    **X** -> $(9)X$(); *X* -> $(5)X$(); ~X~ -> $(2)X$(); !!X!! -> $(4)X$();
    [[статья]] и [[статья|текст]] -> ссылка на статью книги.
    """
    lines = text.strip("\n").split("\n")
    out = []
    para = []

    def close_para():
        if para:
            out.append(("p", " ".join(s.strip() for s in para)))
            para.clear()

    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            close_para()
            out.append(("blank", ""))
        elif s.lstrip().startswith("- "):
            close_para()
            out.append(("li", s.lstrip()[2:].strip()))
        elif s.startswith("  ") and out and out[-1][0] == "li" and not para:
            out[-1] = ("li", out[-1][1] + " " + s.strip())
        else:
            para.append(s)
    close_para()
    res = ""
    prev = None
    for kind, s in out:
        if kind == "blank":
            prev = "blank" if prev != "start" else prev
            continue
        if kind == "li":
            res += "$(li)" + s
        else:
            if res:
                res += "$(br2)" if prev == "blank" or prev == "li" else " "
            res += s
        prev = kind
    return inline(res, ctx)


def inline(s, ctx):
    def link(m):
        target, _, label = m.group(1).partition("|")
        eid = ctx.book.find_entry(target.strip(), ctx.where)
        if not label:
            label = ctx.book.entry_name(eid) if eid else target
        return f"$(l:{eid or target}){label}$(/l)"

    s = re.sub(r"\[\[([^\]]+)\]\]", link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"$(9)\1$()", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"$(5)\1$()", s)
    s = re.sub(r"~(.+?)~", r"$(2)\1$()", s)
    s = re.sub(r"!!(.+?)!!", r"$(4)\1$()", s)
    return s


# ---------------------------------------------------------------- модель книги

class Ctx:
    def __init__(self, book, where):
        self.book = book
        self.where = where


class Entry:
    def __init__(self, cat, eid, where):
        self.cat = cat
        self.id = eid  # "power/eu"
        self.where = where
        self.props = {}
        self.pages = []  # (тип, аргументы, заголовок, тело, где)
        self.provides = []


class Category:
    def __init__(self, cid, where):
        self.id = cid
        self.where = where
        self.props = {}
        self.entries = []


class Book:
    def __init__(self, bid):
        self.id = bid
        self.dir = os.path.join(BOOKS, bid)
        self.meta = load_json(os.path.join(self.dir, "book.json"))
        self.categories = []
        self.entries = {}
        self.groups = {}
        self.shots = []
        self.templates = {}
        self.parse()

    # --- чтение

    def parse(self):
        self.parse_unlocks(os.path.join(self.dir, "unlocks.txt"))
        for fn in sorted(os.listdir(self.dir)):
            if fn.endswith(".txt") and fn != "unlocks.txt":
                self.parse_file(os.path.join(self.dir, fn))

    def parse_unlocks(self, path):
        if not os.path.exists(path):
            return
        cur = None
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                where = f"{os.path.basename(path)}:{n}"
                if s.startswith("@group "):
                    cur = s[7:].strip()
                    self.groups[cur] = {"items": [], "where": where, "entries": []}
                elif s.startswith("- ") and cur:
                    ref, _, name = s[2:].partition("|")
                    self.groups[cur]["items"].append((ref.strip(), name.strip() or None, where))
                else:
                    err(where, f"непонятная строка: {s}")

    def parse_file(self, path):
        fname = os.path.basename(path)
        cat = None
        entry = None
        page = None
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        for n, line in enumerate(lines, 1):
            where = f"{fname}:{n}"
            if line.startswith("@category "):
                cat = Category(line[10:].strip(), where)
                self.categories.append(cat)
                entry = page = None
                continue
            if line.startswith("@entry "):
                if not cat:
                    err(where, "статья вне раздела")
                    continue
                eid = f"{cat.id}/{line[7:].strip()}"
                entry = Entry(cat, eid, where)
                if eid in self.entries:
                    err(where, f"статья {eid} уже есть")
                self.entries[eid] = entry
                cat.entries.append(entry)
                page = None
                continue
            if line.startswith("== "):
                if not entry:
                    err(where, "страница вне статьи")
                    continue
                head = line[3:]
                title = None
                if " | " in head:
                    head, title = head.split(" | ", 1)
                parts = head.split()
                page = [parts[0], parts[1:], title, [], where]
                entry.pages.append(page)
                continue
            if page is not None:
                page[3].append(line)
                continue
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            m = re.match(r"^([a-z_]+):\s*(.*)$", s)
            if not m:
                err(where, f"непонятная строка: {s}")
                continue
            target = entry if entry else cat
            if target is None:
                err(where, "свойство вне раздела")
                continue
            target.props[m.group(1)] = m.group(2)

    # --- поиск

    def find_entry(self, target, where):
        if target in self.entries:
            return target
        cands = [e for e in self.entries if e.split("/", 1)[1] == target]
        if len(cands) == 1:
            return cands[0]
        err(where, f"ссылка на статью «{target}»: " + ("нет такой" if not cands else "неоднозначно"))
        return None

    def entry_name(self, eid):
        return self.entries[eid].props.get("name", eid)

    # --- сборка

    def compile(self, out):
        ns = f"{MODID}:{self.id}"
        book_dir = os.path.join(out, "assets", MODID, "patchouli_books", self.id)
        lang_dir = os.path.join(book_dir, "en_us")
        adv_dir = os.path.join(out, "assets", MODID, "advancements", self.id)

        # Группы разблокировки -> достижения
        for g, gd in self.groups.items():
            gd["resolved"] = []
            for ref, name, where in gd["items"]:
                it = resolve(ref, where)
                gd["resolved"].append((it, name or it.name))
            crit = {}
            for i, (it, _) in enumerate(gd["resolved"]):
                if it.trigger is None:
                    err(gd["where"], f"{it.ref}: не годится для открытия статей")
                    continue
                crit[f"has_{i}"] = {"trigger": "minecraft:inventory_changed",
                                    "conditions": {"items": [it.trigger]}}
            write_json(os.path.join(adv_dir, f"{g}.json"),
                       {"criteria": crit, "requirements": [list(crit)]})

        for e in self.entries.values():
            u = e.props.get("unlock")
            if u:
                if u not in self.groups:
                    err(e.where, f"нет группы разблокировки «{u}»")
                else:
                    self.groups[u]["entries"].append(e)
        for g, gd in self.groups.items():
            if not gd["entries"]:
                warn(gd["where"], f"группа {g} ничего не открывает")

        # Статьи
        for cat in self.categories:
            for e in cat.entries:
                data = self.compile_entry(e)
                write_json(os.path.join(lang_dir, "entries", e.id + ".json"), data)

        # Разделы
        for cat in self.categories:
            p = cat.props
            locked = all(e.props.get("unlock") for e in cat.entries)
            d = {"name": p.get("name", cat.id), "description": p.get("description", ""),
                 "icon": resolve(p.get("icon", "minecraft:book"), cat.where).stack.split(",")[0],
                 "sortnum": int(p.get("sort", 0))}
            if p.get("parent"):
                d["parent"] = p["parent"]
            if locked:
                d["secret"] = True
            write_json(os.path.join(lang_dir, "categories", cat.id + ".json"), d)

        for name, tpl in self.templates.items():
            write_json(os.path.join(lang_dir, "templates", name + ".json"), tpl)

        meta = dict(self.meta)
        write_json(os.path.join(book_dir, "book.json"), meta)
        return ns

    def compile_entry(self, e):
        p = e.props
        pages = []
        first = True
        for kind, args, title, body, where in e.pages:
            ctx = Ctx(self, where)
            text = "\n".join(body)
            fn = getattr(self, "page_" + kind, None)
            if fn is None:
                err(where, f"неизвестный тип страницы {kind}")
                continue
            res = fn(e, args, title, text, ctx, first)
            if res is None:
                continue
            for pg in (res if isinstance(res, list) else [res]):
                pages.append(pg)
                first = False
        nxt = self.next_page(e)
        if nxt:
            pages.extend(nxt)
        icon = p.get("icon")
        if not icon:
            err(e.where, "у статьи нет icon")
            icon = "minecraft:book"
        d = {"name": p.get("name", e.id), "category": e.cat.id,
             "icon": resolve(icon, e.where).stack.split(",")[0],
             "sortnum": int(p.get("sort", 0)), "pages": pages}
        if p.get("unlock"):
            d["advancement"] = f"{MODID}:{self.id}/{p['unlock']}"
            d["secret"] = True
        if p.get("priority") == "yes":
            d["priority"] = True
        if p.get("read_by_default") == "yes":
            d["read_by_default"] = True
        if str_width(d["name"]) > 104:  # кнопка статьи 116 px, текст начинается с 12 px
            warn(e.where, f"длинное название статьи ({str_width(d['name'])} px), в списке может не влезть")
        return d

    # --- страницы

    def check_text(self, text, start_y, where, width=116, bottom=PAGE_BOTTOM):
        b = text_bottom(text, start_y, width)
        if b > bottom:
            over = (b - bottom + 8) // 9
            err(where, f"текст не влезает на страницу: лишних строк ≈{over}")

    def split_pages(self, t, start, where):
        """Делит текст на части по абзацам и пунктам списка так, чтобы каждая помещалась.
        Первая часть начинается с высоты start, остальные — с верха страницы без заголовка."""
        blocks = re.split(r"(?=\$\(br2\)|\$\(li\d?\))", t)
        blocks = [b for b in blocks if b]
        parts = []
        cur = ""
        y0 = start
        for b in blocks:
            cand = cur + b
            body = cand[6:] if cand.startswith("$(br2)") else cand
            top = y0 + (9 if body.startswith("$(li") else 0)
            if cur and text_bottom(body, top) > PAGE_BOTTOM:
                parts.append(cur[6:] if cur.startswith("$(br2)") else cur)
                cur = b
                y0 = -4
            else:
                cur = cand
        if cur:
            parts.append(cur[6:] if cur.startswith("$(br2)") else cur)
        for i, ptxt in enumerate(parts):
            top = (start if i == 0 else -4) + (9 if ptxt.startswith("$(li") else 0)
            if text_bottom(ptxt, top) > PAGE_BOTTOM:
                err(where, "абзац не помещается даже на отдельную страницу — разбей его")
        return parts

    def page_text(self, e, args, title, text, ctx, first):
        t = markup(text, ctx)
        start = 22 if first else (12 if title else -4)
        parts = self.split_pages(t, start, ctx.where)
        res = []
        for i, ptxt in enumerate(parts):
            d = {"type": "text", "text": ptxt}
            if title and i == 0:
                d["title"] = title
            res.append(d)
        return res

    def page_spotlight(self, e, args, title, text, ctx, first):
        it = resolve(args[0], ctx.where)
        e.provides.append(it)
        t = markup(text, ctx)
        parts = self.split_pages(t, 40, ctx.where)
        d = {"type": "spotlight", "item": it.stack.split(",")[0], "text": parts[0]}
        if title:
            d["title"] = title
        if "link" in args[1:]:
            d["link_recipe"] = True
        return [d] + [{"type": "text", "text": p} for p in parts[1:]]

    def page_craft(self, e, args, title, text, ctx, first):
        """== craft <предмет> [номер рецепта] — рецепт верстака из файлов IC2."""
        idx = int(args[1]) if len(args) > 1 else 1
        r = find_recipe(args[0], idx, ctx.where)
        if not r:
            return None
        return self.craft_page(e, r["grid"], r["out"], title, text, ctx, r.get("shapeless"))

    def page_grid(self, e, args, title, text, ctx, first):
        """== grid <результат>, затем 3 строки по 3 предмета («_» — пусто), потом подпись."""
        lines = [ln for ln in text.split("\n")]
        rows = []
        while lines and len(rows) < 3:
            ln = lines.pop(0)
            if not ln.strip():
                if rows:
                    break
                continue
            rows.append(ln.split())
        grid = []
        for r in range(3):
            row = rows[r] if r < len(rows) else []
            for c in range(3):
                tok = row[c] if c < len(row) else "_"
                grid.append(None if tok == "_" else tok)
        return self.craft_page(e, grid, args[0], title, "\n".join(lines), ctx, "shapeless" in args[1:])

    def craft_page(self, e, grid, out, title, text, ctx, shapeless):
        d = {"type": f"{MODID}:ic2_craft"}
        self.ensure_craft_template()
        for i, g in enumerate(grid):
            if g:
                d[f"a{i + 1}"] = resolve(g, ctx.where).stack
        o = resolve(out, ctx.where)
        e.provides.append(o)
        d["out"] = o.stack
        t = markup(text, ctx) if text.strip() else ""
        if shapeless:
            t = ("Без формы: ингредиенты кладутся в любые ячейки." + (" " + t if t else ""))
        if title:
            d["title"] = title
        if t:
            d["text"] = t
            self.check_text(t, 78 if not title else 88, ctx.where)
        return d

    def page_machine(self, e, args, title, text, ctx, first):
        """== machine <машина>: строки «вход -> выход [выход2 ...]», остальное — подпись."""
        m = resolve(args[0], ctx.where)
        rows = []
        cap = []
        for ln in text.split("\n"):
            if "->" in ln:
                left, right = ln.split("->", 1)
                outs = right.split()
                ins = [x.strip() for x in left.split(" + ")]
                if len(ins) > 1 and len(outs) > 1:
                    err(ctx.where, "строка с несколькими входами может иметь только один выход")
                rows.append((ins if len(ins) > 1 else left.strip(), outs))
            elif ln.strip() or cap:
                cap.append(ln)
        if not rows:
            err(ctx.where, "у страницы machine нет строк рецептов")
            return None
        for inp, outs in rows:
            if isinstance(inp, list):
                continue  # несколько входов — у машин из ini таких рецептов нет
            ok = machine_recipe_exists(m.ref, inp, outs)
            if ok is False:
                warn(ctx.where, f"в рецептах {m.ref} нет строки {inp} -> {' '.join(outs)}")
        t = markup("\n".join(cap), ctx) if any(c.strip() for c in cap) else ""
        # Строки, которые не помещаются, переносятся на следующую страницу; подпись — на последней
        row_h = lambda outs: 28 if len(outs) == 1 else 54
        chunks = []
        cur = []
        y = 16 if title else 2
        for r in rows:
            if cur and y + row_h(r[1]) > PAGE_BOTTOM + 9:
                chunks.append(cur)
                cur = []
                y = 2
            cur.append(r)
            y += row_h(r[1])
        chunks.append(cur)
        if t:
            last_y = (16 if title and len(chunks) == 1 else 2) + sum(row_h(r[1]) for r in chunks[-1])
            if text_bottom(t, last_y + 4) > PAGE_BOTTOM:
                chunks.append([])
        pages = []
        for n, chunk in enumerate(chunks):
            titled = bool(title) and n == 0
            is_last = n == len(chunks) - 1
            if not chunk:
                pages.append({"type": "text", "text": t})
                continue
            layout = tuple(f"x{len(i)}" if isinstance(i, list) else len(o) for i, o in chunk)
            name, height = self.ensure_machine_template(layout, titled)
            d = {"type": f"{MODID}:{name}", "m": m.stack}
            if titled:
                d["title"] = title
            for i, (inp, outs) in enumerate(chunk, 1):
                if isinstance(inp, list):
                    for k, x in enumerate(inp, 1):
                        d[f"i{i}_{k}"] = resolve(x, ctx.where).stack
                else:
                    d[f"i{i}"] = resolve(inp, ctx.where).stack
                for j, o in enumerate(outs, 1):
                    it = resolve(o, ctx.where)
                    e.provides.append(it)
                    d[f"o{i}_{j}"] = it.stack
            if is_last and t:
                d["text"] = t
                self.check_text(t, height + 4, ctx.where)
            pages.append(d)
        return pages

    def page_image(self, e, args, title, text, ctx, first):
        imgs = [f"{MODID}:textures/gui/{self.id}/{a}" for a in args]
        for a in args:
            path = os.path.join(ROOT, "tomes", "resources", "assets", MODID, "textures", "gui", self.id, a)
            if not os.path.exists(path):
                err(ctx.where, f"нет картинки {a}")
        t = markup(text, ctx)
        self.check_text(t, 120, ctx.where)
        d = {"type": "image", "images": imgs, "border": True, "text": t}
        if title:
            d["title"] = title
        return d

    def page_shot(self, e, args, title, text, ctx, first):
        """== shot <файл.png> | Заголовок
        Что снять (для списка скриншотов)
        --
        Подпись в книге
        Пока картинки нет, страница в книгу не попадает, а попадает в список скриншотов."""
        what, _, cap = text.partition("\n--\n")
        fname = args[0]
        path = os.path.join(ROOT, "tomes", "resources", "assets", MODID, "textures", "gui", self.id, fname)
        self.shots.append({"file": fname, "entry": e.id, "entry_name": e.props.get("name", e.id),
                           "title": title or "", "what": what.strip(), "have": os.path.exists(path)})
        if not os.path.exists(path):
            return None
        return self.page_image(e, [fname], title, cap, ctx, first)

    def page_multiblock(self, e, args, title, text, ctx, first):
        """== multiblock | Название
        строки-слои сверху вниз, разделённые «---»; затем «ключ = предмет»; затем «--» и подпись."""
        spec, _, cap = text.partition("\n--\n")
        layers = [[]]
        mapping = {}
        for ln in spec.split("\n"):
            if not ln.strip():
                continue
            if ln.strip() == "---":
                layers.append([])
            elif re.match(r"^\S\s*=\s*\S", ln.strip()):
                k, v = ln.split("=", 1)
                mapping[k.strip()] = v.strip()
            else:
                layers[-1].append(ln.rstrip("\n"))
        t = markup(cap, ctx)
        self.check_text(t, 115, ctx.where)
        d = {"type": "multiblock", "name": title or "", "text": t, "enable_visualize": True,
             "multiblock": {"pattern": layers, "mapping": mapping}}
        return d

    def page_entity(self, e, args, title, text, ctx, first):
        t = markup(text, ctx)
        self.check_text(t, 115, ctx.where)
        d = {"type": "entity", "entity": args[0], "text": t}
        if title:
            d["name"] = title
        return d

    def page_relations(self, e, args, title, text, ctx, first):
        ents = [self.find_entry(a, ctx.where) for a in args]
        t = markup(text, ctx)
        self.check_text(t, 22 + len(ents) * 11, ctx.where)
        d = {"type": "relations", "entries": [x for x in ents if x], "text": t}
        if title:
            d["title"] = title
        return d

    def page_raw(self, e, args, title, text, ctx, first):
        return json.loads(text)

    # --- «Что дальше»

    def next_page(self, e):
        mode = e.props.get("next", "auto").strip()
        if mode == "none":
            return None
        own = e.props.get("unlock")
        if mode == "auto":
            prov = set()
            for it in e.provides:
                prov |= stack_keys(it)
            for ref in e.props.get("provides", "").split(","):
                if ref.strip():
                    prov |= stack_keys(resolve(ref.strip(), e.where))
            groups = []
            for g, gd in self.groups.items():
                if g == own or not gd["entries"]:
                    continue
                if any(stack_keys(it) & prov for it, _ in gd["resolved"]):
                    groups.append(g)
        else:
            groups = [g.strip() for g in mode.split(",") if g.strip()]
            for g in groups:
                if g not in self.groups:
                    err(e.where, f"next: нет группы {g}")
            groups = [g for g in groups if g in self.groups]
        if not groups:
            return None
        text = "Следующие статьи появятся в книге, когда у тебя в инвентаре окажется:"
        for g in groups:
            gd = self.groups[g]
            names = []
            for it, name in gd["resolved"]:
                if name not in names:
                    names.append(name)
            opens = sorted(gd["entries"], key=lambda x: (int(x.cat.props.get("sort", 0)), int(x.props.get("sort", 0))))
            text += "$(li)" + " или ".join(f"$(5){n}$()" for n in names) + " — откроется:"
            text += "".join("$(li2)" + x.props.get("name", x.id) for x in opens)
        parts = self.split_pages(text, 12, e.where)
        res = []
        for i, t in enumerate(parts):
            d = {"type": "text", "text": t}
            if i == 0:
                d["title"] = "Что дальше"
            res.append(d)
        return res

    # --- шаблоны

    def ensure_craft_template(self):
        if "ic2_craft" in self.templates:
            return
        comps = [{"type": "image", "image": "patchouli:textures/gui/crafting.png", "x": 7, "y": 8,
                  "u": 0, "v": 0, "width": 100, "height": 62, "texture_width": 128, "texture_height": 128}]
        # Координаты — как у страницы crafting в Patchouli: предметы в 5 px от края фона, шаг 19 px
        for i in range(9):
            comps.append({"type": "item", "item": f"#a{i + 1}", "x": 12 + 19 * (i % 3),
                          "y": 13 + 19 * (i // 3), "guard": f"#a{i + 1}"})
        comps.append({"type": "item", "item": "#out", "x": 88, "y": 32})
        comps.append({"type": "text", "text": "#text", "x": 0, "y": 78, "max_width": 116, "guard": "#text"})
        self.templates["ic2_craft"] = {"components": comps}

    def ensure_machine_template(self, layout, titled):
        """Шаблон страницы машины под нужное число строк и выходов в каждой строке."""
        name = "machine_" + "_".join(str(n) for n in layout) + ("_t" if titled else "")
        comps = []
        y = 14 if titled else 2
        if titled:
            comps.append({"type": "header", "text": "#title", "x": -1, "y": 0})
        tex = "patchouli:textures/gui/crafting.png"

        def frame(x, yy):
            return {"type": "image", "image": tex, "x": x, "y": yy, "u": 11, "v": 71, "width": 24,
                    "height": 24, "texture_width": 128, "texture_height": 128}

        def arrow(x, yy):
            return {"type": "image", "image": tex, "x": x, "y": yy, "u": 38, "v": 79, "width": 10,
                    "height": 9, "texture_width": 128, "texture_height": 128}

        for r, n in enumerate(layout, 1):
            if isinstance(n, str):
                # [вход1][вход2][вход3] -> [выход]; машина показана заголовком или соседней страницей
                k = int(n[1:])
                x = 0
                for j in range(1, k + 1):
                    comps += [frame(x, y), {"type": "item", "item": f"#i{r}_{j}", "x": x + 4, "y": y + 4,
                                            "guard": f"#i{r}_{j}"}]
                    x += 26
                comps += [arrow(x, y + 8), frame(x + 14, y),
                          {"type": "item", "item": f"#o{r}_1", "x": x + 18, "y": y + 4}]
                y += 28
            elif n == 1:
                # [вход] -> машина -> [выход], ширина 100, отступ 8
                comps += [frame(8, y), {"type": "item", "item": f"#i{r}", "x": 12, "y": y + 4},
                          arrow(36, y + 8), {"type": "item", "item": "#m", "x": 50, "y": y + 4},
                          arrow(70, y + 8), frame(84, y), {"type": "item", "item": f"#o{r}_1", "x": 88, "y": y + 4}]
                y += 28
            else:
                # [вход] -> машина  /  -> [выход1][выход2]...
                comps += [frame(29, y), {"type": "item", "item": f"#i{r}", "x": 33, "y": y + 4},
                          arrow(57, y + 8), {"type": "item", "item": "#m", "x": 71, "y": y + 4}]
                y += 24
                w = 10 + 4 + 24 * n + 2 * (n - 1)
                x0 = (116 - w) // 2
                comps.append(arrow(x0, y + 8))
                x = x0 + 14
                for j in range(1, n + 1):
                    comps += [frame(x, y), {"type": "item", "item": f"#o{r}_{j}", "x": x + 4, "y": y + 4}]
                    x += 26
                y += 30
        comps.append({"type": "text", "text": "#text", "x": 0, "y": y + 2, "max_width": 116, "guard": "#text"})
        self.templates[name] = {"components": comps}
        return name, y + 2


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def shots_report(books, path):
    lines = ["# Скриншоты для книг", "",
             "Файл создаётся автоматически при сборке (`python3 build.py`). "
             "Снимок: F1 прячет интерфейс, F2 сохраняет кадр в папку screenshots. "
             "Присылай как есть, обрежу и подгоню сам.", ""]
    for b in books:
        if not b.shots:
            continue
        lines.append(f"## {b.meta.get('name', b.id)}")
        lines.append("")
        lines.append("| Файл | Статья | Что снять | Есть |")
        lines.append("|---|---|---|---|")
        for s in b.shots:
            what = s["what"].replace("\n", " ")
            lines.append(f"| `{s['file']}` | {s['entry_name']} | {what} | {'да' if s['have'] else 'нет'} |")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(out):
    books = []
    for bid in sorted(os.listdir(BOOKS)):
        if os.path.isdir(os.path.join(BOOKS, bid)) and os.path.exists(os.path.join(BOOKS, bid, "book.json")):
            b = Book(bid)
            b.compile(out)
            books.append(b)
    shots_report(books, os.path.join(ROOT, "SCREENSHOTS.md"))
    for w in WARNINGS:
        print("предупреждение:", w)
    if ERRORS:
        print("Ошибки:")
        for x in ERRORS:
            print("  " + x)
        sys.exit(1)
    for b in books:
        n = len(b.entries)
        print(f"{b.id}: {len(b.categories)} разделов, {n} статей")


if __name__ == "__main__":
    main(sys.argv[1])
