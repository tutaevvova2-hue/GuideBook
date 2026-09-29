#!/usr/bin/env python3
"""Проверка качества книги сверх build.py --check.

Запуск: python3 tools/lint_book.py <книга> [--strict]
Ошибки (код возврата 1): запретные слова; главный предмет статьи (== spotlight) есть в stats.md,
а его урона/прочности/защиты в тексте статьи нет.
Предупреждения: нет страниц «Что дальше», нет ни одного == shot в главе, предметы из stats.md,
которых нет ни в одной главе. С --strict предупреждения тоже считаются ошибками.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNED = re.compile(r"\b(мод[а-я]*|модпак[а-я]*|сборк[а-я]*|верси[а-я]+|конфиг[а-я]*|divinerpg|minecraft)\b", re.I)


def norm(text):
    """Числа без разделителей тысяч: «4 000» -> «4000»."""
    return re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", text)


def has_num(text, n):
    n = str(n).rstrip("0").rstrip(".") if "." in str(n) else str(n)
    return re.search(rf"(?<![\d.,]){re.escape(n)}(?![\d])", text) is not None


def load_stats(book):
    weapons, armor = {}, {}
    path = os.path.join(ROOT, "books", book, "sources", "stats.md")
    if not os.path.exists(path):
        return weapons, armor
    for ln in open(path, encoding="utf-8"):
        if not ln.startswith("|"):
            continue
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        m = re.search(r"\(`(\w+)`\)", c[0])
        if m and len(c) >= 4 and re.fullmatch(r"-?\d+", c[2]) and re.fullmatch(r"-?\d+", c[3]):
            weapons[m.group(1)] = (c[0].split(" (")[0], int(c[2]), int(c[3]))
        elif re.fullmatch(r"\w+", c[0]) and len(c) >= 5 and re.fullmatch(r"\d+", c[3]):
            armor[c[0]] = int(c[3])
    return weapons, armor


def parse(book):
    """Список (файл, статья, текст статьи, id главного предмета, число shot)."""
    res = []
    d = os.path.join(ROOT, "books", book)
    for fn in sorted(os.listdir(d)):
        if not re.match(r"\d\d_.*\.txt$", fn):
            continue
        parts = re.split(r"^@entry\s+", open(os.path.join(d, fn), encoding="utf-8").read(), flags=re.M)
        for p in parts[1:]:
            eid = p.split("\n", 1)[0].strip()
            m = re.search(r"^== spotlight\s+\w+:(\w+)", p, re.M)
            res.append((fn, eid, p, m.group(1) if m else None, len(re.findall(r"^== shot\b", p, re.M))))
    return res


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    if not args:
        sys.exit(__doc__)
    book = args[0]
    weapons, armor = load_stats(book)
    entries = parse(book)
    errors, warns, nonext = [], [], {}
    alltext = ""
    files = {}
    for fn, eid, text, spot, shots in entries:
        alltext += "\n" + text
        files.setdefault(fn, [0, 0])
        files[fn][0] += shots
        files[fn][1] += 1
        prose = re.sub(r"\b[a-z0-9_]+:[a-z0-9_#]+", "", text)  # id предметов вроде divinerpg:sword — не текст
        for w in sorted({m.group(0).lower() for m in BANNED.finditer(prose)}):
            errors.append(f"{fn} [{eid}]: запретное слово «{w}» (П-6)")
        t = norm(text)
        if spot in weapons:
            name, dmg, dur = weapons[spot]
            miss = []
            if not has_num(t, dmg):
                miss.append(f"урон {dmg}")
            if dur > 0 and not has_num(t, dur):
                miss.append(f"прочность {dur}")
            if dur < 0 and "не ломается" not in text.lower() and "вечн" not in text.lower():
                miss.append("«не ломается»")
            if miss:
                errors.append(f"{fn} [{eid}]: у главного предмета «{name}» нет в тексте: {', '.join(miss)} (см. sources/stats.md)")
        else:
            m = re.match(r"(\w+?)_(helmet|chestplate|leggings|boots|body|legs)$", spot or "")
            if m and m.group(1) in armor and not has_num(t, armor[m.group(1)]):
                errors.append(f"{fn} [{eid}]: у брони «{m.group(1)}» нет в тексте защиты {armor[m.group(1)]} (sources/stats.md)")
        if not re.search(r"^== \w+ \|\s*Что дальше|^== text \|\s*Что дальше", text, re.M | re.I):
            nonext.setdefault(fn, []).append(eid)
    for fn, ids in nonext.items():
        warns.append(f"{fn}: нет страницы «Что дальше» (П-20) в статьях: {', '.join(ids)}")
    for fn, (shots, n) in files.items():
        if shots == 0:
            warns.append(f"{fn}: в главе нет ни одного == shot (скриншоты)")
    for fn in files:
        num = int(fn[:2]) + 1  # 00_start.txt — глава 1
        dossier = os.path.join(ROOT, "books", book, "sources", "research", f"ch{num}.md")
        if not os.path.exists(dossier):
            warns.append(f"{fn}: нет досье sources/research/ch{num}.md (задание ИССЛЕДОВАНИЕ)")
        else:
            urls = set(re.findall(r"https?://[^\s)>\]]+", open(dossier, encoding="utf-8").read()))
            if len(urls) < 3:
                warns.append(f"{fn}: в досье ch{num}.md меньше 3 источников ({len(urls)})")
    names = {k: v[0] for k, v in weapons.items()}
    low = alltext.lower()
    missing = [n for k, n in names.items() if k not in alltext and n.lower() not in low]
    if missing:
        warns.append(f"в главах не упомянуто предметов из stats.md: {len(missing)} из {len(names)}: " + ", ".join(missing[:25]) + ("…" if len(missing) > 25 else ""))
    print(f"Книга {book}: статей {len(entries)}")
    for e in errors:
        print("ОШИБКА:", e)
    for w in warns:
        print("предупреждение:", w)
    if not errors and not (strict and warns):
        print("LINT OK")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
