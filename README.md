# GuideBook — книги-справочники для сборки на Minecraft 1.12.2

Здесь исходники мода **Tomes**: в нём живут книги Patchouli для сборки.
Сейчас готов первый том — «Промышленный справочник» (IndustrialCraft 2 с главами о Gravitation Suite и Energy Control).

- [REQUIREMENTS.md](REQUIREMENTS.md) — все договорённости о книгах, пронумерованные (П-1, П-2…).
- [SCREENSHOTS.md](SCREENSHOTS.md) — какие скриншоты нужны для книг (создаётся при сборке).
- [books/FORMAT.md](books/FORMAT.md) — как писать статьи.

## Сборка

Нужны Python 3 и JDK 8 или новее.

```
python3 build.py            # проверка и сборка dist/Tomes-1.12.2-<версия>.jar
python3 build.py --check    # только проверка книг
python3 tools/patch_patchouli.py   # dist/Patchouli-1.0-23.6-tomes.jar
```

В игру ставятся оба файла из `dist/`: Tomes и изменённый Patchouli
(одна кнопка «История», шкала прогресса считает все статьи, русские подписи,
ссылки на закрытые статьи не открываются).

## Что где лежит

| Путь | Что |
|---|---|
| `books/<книга>/` | текст книг в разметке Tomes |
| `tomes/resources/` | неизменяемые файлы мода: `mcmod.info`, текстуры книги, модель, рецепт книги |
| `tomes/java/` | единственный класс мода |
| `tools/tome.py` | компилятор разметки в JSON Patchouli |
| `tools/ic2data.py` | выгрузка предметов, рецептов и перевода из jar IC2 в `tools/data/ic2.json` |
| `tools/show.py` | поиск по данным IC2: рецепты, применения, названия |
| `tools/data/` | данные: IC2, ванильные и прочие предметы, ширины символов шрифта |
| `tools/patches/` | исходник правки Patchouli (ссылки на закрытые статьи) |
| `vendor/` | Patchouli с правками и файлы, которые подменяются при сборке |

Версия мода — в `tomes/resources/mcmod.info`.
