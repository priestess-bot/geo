from __future__ import annotations

import csv
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from re import match
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree


XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XLSX_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def prompt_import_file_to_csv(*, file_bytes: bytes, filename: str) -> tuple[str, str]:
    normalized_filename = filename.strip().lower()
    if not file_bytes:
        raise ValueError("prompt import file is empty")
    if normalized_filename.endswith((".csv", ".txt")):
        return file_bytes.decode("utf-8-sig"), "csv"
    if normalized_filename.endswith(".xlsx"):
        try:
            return _xlsx_first_sheet_to_csv(file_bytes), "xlsx"
        except BadZipFile as exc:
            raise ValueError("xlsx file is not a valid workbook") from exc
        except KeyError as exc:
            raise ValueError("xlsx workbook is missing required worksheet parts") from exc
        except ElementTree.ParseError as exc:
            raise ValueError("xlsx workbook contains invalid XML") from exc
    raise ValueError("unsupported prompt import file type; expected .csv or .xlsx")


def _xlsx_first_sheet_to_csv(file_bytes: bytes) -> str:
    with ZipFile(BytesIO(file_bytes)) as workbook:
        shared_strings = _read_shared_strings(workbook)
        sheet_path = _first_sheet_path(workbook)
        rows = _read_sheet_rows(workbook, sheet_path=sheet_path, shared_strings=shared_strings)
    if not rows:
        raise ValueError("xlsx sheet is empty")
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue()


def _read_shared_strings(workbook: ZipFile) -> list[str]:
    try:
        payload = workbook.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(payload)
    strings: list[str] = []
    for item in root.findall(f".//{{{XLSX_MAIN_NS}}}si"):
        parts = [text_node.text or "" for text_node in item.iter(f"{{{XLSX_MAIN_NS}}}t")]
        strings.append("".join(parts))
    return strings


def _first_sheet_path(workbook: ZipFile) -> str:
    workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    sheets = workbook_root.findall(f".//{{{XLSX_MAIN_NS}}}sheet")
    if not sheets:
        raise ValueError("xlsx workbook has no worksheets")
    rel_id = sheets[0].attrib.get(f"{{{XLSX_DOC_REL_NS}}}id")
    if not rel_id:
        raise ValueError("xlsx first worksheet is missing relationship id")
    rels_root = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    for relationship in rels_root.findall(f".//{{{XLSX_REL_NS}}}Relationship"):
        if relationship.attrib.get("Id") == rel_id:
            target = relationship.attrib.get("Target", "")
            if not target:
                raise ValueError("xlsx first worksheet relationship has no target")
            if target.startswith("/"):
                return target.lstrip("/")
            return str(PurePosixPath("xl") / target)
    raise ValueError("xlsx first worksheet relationship not found")


def _read_sheet_rows(workbook: ZipFile, *, sheet_path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(workbook.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(f".//{{{XLSX_MAIN_NS}}}sheetData/{{{XLSX_MAIN_NS}}}row"):
        cells: dict[int, str] = {}
        max_index = -1
        for cell in row.findall(f"{{{XLSX_MAIN_NS}}}c"):
            column_index = _column_index(cell.attrib.get("r", ""))
            if column_index is None:
                column_index = max_index + 1
            max_index = max(max_index, column_index)
            cells[column_index] = _cell_value(cell, shared_strings)
        if max_index >= 0:
            rows.append([cells.get(index, "") for index in range(max_index + 1)])
    while rows and not any(value.strip() for value in rows[-1]):
        rows.pop()
    return rows


def _column_index(cell_ref: str) -> int | None:
    matched = match(r"([A-Z]+)", cell_ref.upper())
    if not matched:
        return None
    index = 0
    for char in matched.group(1):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text_node.text or "" for text_node in cell.iter(f"{{{XLSX_MAIN_NS}}}t"))
    value_node = cell.find(f"{{{XLSX_MAIN_NS}}}v")
    raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value
