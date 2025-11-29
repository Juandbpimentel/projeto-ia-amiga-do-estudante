import re
from bs4 import Tag, BeautifulSoup
from typing import List, Dict
from .utils import _normalize_token


# parse HTML table rows and fallback to plain text rows


def _extract_table_context(table: Tag) -> str:
    context: List[str] = []
    for sibling in table.find_all_previous():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in {"h1", "h2", "h3", "h4", "p"}:
            text = sibling.get_text(" ", strip=True)
            if text:
                context.append(text)
        if len(context) >= 2:
            break
    return " | ".join(reversed(context))


def _parse_google_table(table: Tag) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    header_cells = table.find("tr")
    if not header_cells:
        return rows
    headers = [
        cell.get_text(" ", strip=True) or f"Coluna {idx + 1}"
        for idx, cell in enumerate(header_cells.find_all(["th", "td"]))
    ]
    data_rows = table.find_all("tr")[1:]
    context = _extract_table_context(table)

    # Detect typical timetable: first header is 'Hor' or similar -> create per-cell rows
    is_timetable = False
    if headers:
        first_header_norm = _normalize_token(headers[0] or "")
        if "hor" in first_header_norm or "horario" in first_header_norm:
            is_timetable = True

    for tr in data_rows:
        cells = tr.find_all(["td", "th"])
        values = [cell.get_text("\n", strip=True) for cell in cells]
        if not any(values):
            continue
        if is_timetable and len(values) >= 2:
            # first cell is the time range
            time_range = values[0]
            # iterate for each day column
            for idx in range(1, min(len(headers), len(values))):
                day_header = headers[idx]
                cell_text = values[idx]
                if not cell_text:
                    continue
                row = {
                    "context": context,
                    "_row_text": cell_text,
                    "Horário": time_range,
                    "Dia": day_header,
                }
                # keep full cell splitted into Coluna fields for compatibility
                parts = [
                    p.strip()
                    for p in re.split(r"\n+|[\u00A0]\s*|\s{2,}", cell_text)
                    if p.strip()
                ]
                for pidx, p in enumerate(parts):
                    row[f"Coluna {pidx + 1}"] = p
                rows.append(row)
        else:
            row: Dict[str, str] = {"context": context, "_row_text": " | ".join(values)}
            for idx, header in enumerate(headers):
                row[header] = values[idx] if idx < len(values) else ""
            rows.append(row)
    return rows


def _parse_plain_rows_from_doc(doc_soup: BeautifulSoup) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    text = doc_soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header_idx = None
    for idx, line in enumerate(lines):
        if re.search(r"\bhor(?:\.|ario)?\b", _normalize_token(line)) and (
            "segunda" in _normalize_token(line)
            or "terca" in _normalize_token(line)
            or "quarta" in _normalize_token(line)
        ):
            header_idx = idx
            break
    if header_idx is not None:
        header_line = lines[header_idx]
        cols = [c.strip() for c in re.split(r"\||\t|\s{2,}", header_line) if c.strip()]
        for line in lines[header_idx + 1 :]:
            parts = [p.strip() for p in re.split(r"\||\t|\s{2,}", line) if p.strip()]
            if len(parts) < 2:
                continue
            time_range = parts[0]
            for i in range(1, min(len(cols), len(parts))):
                day = cols[i]
                cell_text = parts[i]
                if not cell_text:
                    continue
                row: Dict[str, str] = {
                    "context": "",
                    "_row_text": cell_text,
                    "Horário": time_range,
                    "Dia": day,
                }
                for pidx, p in enumerate(
                    [
                        p.strip()
                        for p in re.split(r"\\n+|[\\u00A0]\s*|\s{2,}", cell_text)
                        if p.strip()
                    ]
                ):
                    row[f"Coluna {pidx + 1}"] = p
                rows.append(row)
        return rows
    for line in lines:
        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
        elif "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]
        if len(parts) < 2:
            continue
        if not any(re.search(r"\w+", p) for p in parts):
            continue
        row: Dict[str, str] = {"_row_text": " | ".join(parts)}
        for idx, p in enumerate(parts):
            row[f"Coluna {idx + 1}"] = p
        rows.append(row)
    return rows
