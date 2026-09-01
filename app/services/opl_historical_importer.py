import base64
import io
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

MARKERS = {
    "ONE POINT LESSON": 6,
    "OPL N": 5,
    "TITOLO": 3,
    "REPARTO": 3,
    "LINEA": 3,
    "TIPO": 2,
    "AREA OPL": 2,
}

LABELS = {
    "numero_originale": ["OPL N", "OPL NO", "N OPL", "NUMERO OPL"],
    "titolo": ["TITOLO"],
    "tipo_opl": ["TIPO"],
    "reparto_originale": ["REPARTO"],
    "linea_originale": ["LINEA"],
    "area_opl": ["AREA OPL COLORE BORDO", "AREA OPL"],
}

EMPTY_VALUES = {"", "-", "--", "---", "- - -", "N/A", "NONE"}
KNOWN_LABELS = {
    "OPL N", "OPL NO", "N OPL", "NUMERO OPL", "TITOLO", "TIPO", "AUTORE",
    "COMPILATO DA", "REPARTO", "LINEA", "PROBLEMA", "CAUSA", "MIGLIORAMENTO",
    "DATA", "VERIFICA DELL APPRENDIMENTO", "AREA OPL", "AREA OPL COLORE BORDO",
}


def normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return re.sub(r"\s+", " ", str(value).replace("\n", " ").replace("\r", " ").strip())


def normalize_key(value):
    text = unicodedata.normalize("NFKD", normalize_text(value).upper())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def is_real_value(value):
    key = normalize_key(value)
    if key in EMPTY_VALUES or key in KNOWN_LABELS:
        return False
    return not any(key == label or key.startswith(label + " ") for label in KNOWN_LABELS)


def sheet_cells(worksheet):
    return [cell for row in worksheet.iter_rows() for cell in row if cell.value not in (None, "")]


def sheet_score(worksheet):
    values = [normalize_key(cell.value) for cell in sheet_cells(worksheet)]
    score = sum(weight for marker, weight in MARKERS.items() if any(marker in value for value in values))
    core = sum(1 for marker in ("OPL N", "TITOLO", "REPARTO", "LINEA") if any(marker in value for value in values))
    score += min(sum(1 for value in values if value and value not in EMPTY_VALUES) // 10, 4)
    if worksheet.sheet_state != "visible":
        score -= 8
    if core < 2:
        score -= 10
    return score


def select_opl_sheet(workbook):
    ranked = sorted(
        ((sheet_score(worksheet), index, worksheet) for index, worksheet in enumerate(workbook.worksheets)),
        key=lambda item: (item[0], -item[1]),
        reverse=True,
    )
    if not ranked or ranked[0][0] < 5:
        raise ValueError("Nessun foglio OPL riconoscibile")
    return ranked[0][2]


def merged_value(worksheet, row, column):
    value = worksheet.cell(row=row, column=column).value
    if value not in (None, ""):
        return value
    coordinate = worksheet.cell(row=row, column=column).coordinate
    for merged_range in worksheet.merged_cells.ranges:
        if coordinate in merged_range:
            return worksheet.cell(merged_range.min_row, merged_range.min_col).value
    return None


def find_value_near_label(worksheet, aliases):
    normalized_aliases = [normalize_key(alias) for alias in aliases]
    for cell in sheet_cells(worksheet):
        key = normalize_key(cell.value)
        if not any(key == alias or key.startswith(alias + " ") for alias in normalized_aliases):
            continue
        inline = normalize_text(cell.value)
        if ":" in inline:
            suffix = inline.split(":", 1)[1].strip()
            if is_real_value(suffix):
                return suffix
        candidates = []
        for offset in range(1, 8):
            candidates.append(merged_value(worksheet, cell.row, cell.column + offset))
        for offset in range(1, 4):
            candidates.append(merged_value(worksheet, cell.row + offset, cell.column))
        for candidate in candidates:
            if is_real_value(candidate):
                return normalize_text(candidate)
    return ""


def find_date(worksheet):
    candidates = []
    for cell in sheet_cells(worksheet):
        key = normalize_key(cell.value)
        if key != "DATA" and not key.startswith("DATA "):
            continue
        inline = normalize_text(cell.value)
        match = re.search(r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{1,2}-\d{1,2})", inline)
        if match:
            candidates.append(match.group(1))
        for offset in range(1, 8):
            candidates.append(merged_value(worksheet, cell.row, cell.column + offset))
        for offset in range(1, 4):
            candidates.append(merged_value(worksheet, cell.row + offset, cell.column))
    for candidate in candidates:
        if isinstance(candidate, datetime):
            return candidate.date().isoformat()
        if isinstance(candidate, date):
            return candidate.isoformat()
        text = normalize_text(candidate)
        for date_format in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, date_format).date().isoformat()
            except ValueError:
                pass
    return ""


def number_from_value(value, filename):
    sources = [normalize_text(value), filename]
    for source in sources:
        match = re.search(r"(?i)(?:OPL\s*[-_ ]*)?([0-9]{1,8})(?:\s*[_/-]\s*([0-9]{1,3}))?", source)
        if match:
            base_number = int(match.group(1))
            revision = match.group(2)
            original = f"OPL-{base_number}"
            if revision:
                original += f"_{int(revision)}"
            return original, f"OPL-{base_number}", base_number
    return "", "", None


def normalize_department(value):
    original = normalize_text(value)
    aliases = {
        "MOD NORD": "Modellaggio Nord",
        "MODELLAGGIO NORD": "Modellaggio Nord",
        "MOD SUD": "Modellaggio Sud",
        "MODELLAGGIO SUD": "Modellaggio Sud",
        "CONFEZIONE": "Confezione",
    }
    return aliases.get(normalize_key(original), original.title() if original else "")


def normalize_line(value):
    original = normalize_text(value)
    match = re.search(r"(BINDLER|BETTI|MOB)\s*([0-9]+)", normalize_key(original))
    if match:
        prefix = "Bindler" if match.group(1) in {"BINDLER", "MOB"} else "Betti"
        return f"{prefix} {match.group(2)}"
    return original.title() if original else ""


def render_sheet(contents, filename, selected_sheet):
    if not shutil.which("libreoffice") or not shutil.which("pdftoppm"):
        return None
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / Path(filename).name
        source.write_bytes(contents)
        workbook = load_workbook(source)
        for worksheet in workbook.worksheets:
            worksheet.sheet_state = "visible" if worksheet.title == selected_sheet else "hidden"
        workbook.active = workbook.sheetnames.index(selected_sheet)
        prepared = temp / f"prepared_{source.name}"
        workbook.save(prepared)
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(temp), str(prepared)],
            capture_output=True,
            timeout=90,
            check=False,
        )
        pdf = temp / f"{prepared.stem}.pdf"
        if not pdf.exists():
            return None
        output = temp / "preview"
        subprocess.run(
            ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "120", str(pdf), str(output)],
            capture_output=True,
            timeout=90,
            check=False,
        )
        png = temp / "preview.png"
        if not png.exists():
            return None
        return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")


def analyze_excel(contents, filename, include_preview=True):
    workbook = load_workbook(io.BytesIO(contents), data_only=True, read_only=False)
    worksheet = select_opl_sheet(workbook)
    extracted = {field: find_value_near_label(worksheet, aliases) for field, aliases in LABELS.items()}
    numero_originale, numero, numero_progressivo = number_from_value(extracted["numero_originale"], filename)
    reparto = normalize_department(extracted["reparto_originale"])
    linea = normalize_line(extracted["linea_originale"])
    data_documento = find_date(worksheet)
    warnings = []
    if not numero:
        warnings.append("Numero OPL non riconosciuto")
    if not extracted["titolo"]:
        warnings.append("Titolo non riconosciuto")
    if not reparto:
        warnings.append("Reparto non riconosciuto")
    if not linea:
        warnings.append("Linea non riconosciuta")
    recognized = sum(bool(value) for value in [numero, extracted["titolo"], reparto, linea, extracted["area_opl"], extracted["tipo_opl"], data_documento])
    confidence = round((recognized / 7) * 100, 1)
    return {
        "filename": filename,
        "sheet": worksheet.title,
        "numero_originale": numero_originale,
        "numero": numero,
        "numero_progressivo": numero_progressivo,
        "titolo": extracted["titolo"],
        "reparto": reparto,
        "linea": linea,
        "area_opl": extracted["area_opl"],
        "tipo_opl": extracted["tipo_opl"],
        "data_documento": data_documento,
        "confidence": confidence,
        "warnings": warnings,
        "preview": render_sheet(contents, filename, worksheet.title) if include_preview else None,
    }
