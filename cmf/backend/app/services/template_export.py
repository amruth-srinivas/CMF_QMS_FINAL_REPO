"""
Template Export Service - PDF, DOCX, XLSX with full design fidelity.
All heavy imports are deferred to function call time (lazy) so the
server can start even if packages are still being installed.
"""
import io, re, json, base64, logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

PAGE_DIMS = {
    'A3': (297, 420), 'A4': (210, 297), 'A5': (148, 210),
    'Letter': (215.9, 279.4), 'Legal': (215.9, 355.6), 'Tabloid': (279.4, 431.8),
}

def _parse_settings(desc: Optional[str]) -> dict:
    defaults = {
        'pageSize': 'A4', 'orientation': 'portrait',
        'margins': {'top': 15, 'bottom': 15, 'left': 15, 'right': 15},
        'headerSpacing': 5, 'footerSpacing': 5,
        'fontFamily': 'Helvetica, Arial, sans-serif',
        'fontSize': '12',
    }
    if not desc:
        return defaults
    try:
        s = json.loads(desc)
        if 'margins' in s:
            defaults['margins'].update(s.pop('margins'))
            s['margins'] = defaults['margins']
        return {**defaults, **s}
    except Exception:
        return defaults

def _clean(html: str) -> str:
    if not html:
        return ""
    return re.sub(r'\s*!important', '', html)

def _css_color(c: Optional[str]) -> Optional[Tuple[int,int,int]]:
    if not c: return None
    c = c.strip()
    m = re.match(r'^#([0-9a-fA-F]{3,8})$', c)
    if m:
        h = m.group(1)
        if len(h) == 3: return (int(h[0]*2,16), int(h[1]*2,16), int(h[2]*2,16))
        if len(h) >= 6: return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))
    m = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', c)
    if m: return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None

def _b64_to_bytes(src: str) -> Optional[bytes]:
    m = re.match(r'data:image/[^;]+;base64,(.+)', src)
    if m:
        try: return base64.b64decode(m.group(1))
        except Exception: pass
    return None

def _parse_inline_style(style_str: str) -> dict:
    result = {}
    if not style_str: return result
    for part in style_str.split(';'):
        part = part.strip()
        if ':' in part:
            k, v = part.split(':', 1)
            result[k.strip().lower()] = v.strip().replace('!important', '').strip()
    return result


# ═══════════════════════════════════════════════════════════════════
# PDF EXPORT
# ═══════════════════════════════════════════════════════════════════
def export_pdf(header_html: str, footer_html: str, description: str, name: str) -> bytes:
    from xhtml2pdf import pisa

    s = _parse_settings(description)
    dim = PAGE_DIMS.get(s['pageSize'], (210, 297))
    pw = dim[0] if s['orientation'] == 'portrait' else dim[1]
    ph = dim[1] if s['orientation'] == 'portrait' else dim[0]
    m = s['margins']
    ff = s.get('fontFamily', 'Helvetica, Arial, sans-serif')
    fs = s.get('fontSize', '12')

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{name}</title>
<style>
@page {{ size: {pw}mm {ph}mm; margin: {m['top']}mm {m['right']}mm {m['bottom']}mm {m['left']}mm; }}
body {{ font-family: {ff}; font-size: {fs}px; line-height: 1.6; color: #1a1a1a; margin: 0; padding: 0; }}
.header {{ padding-bottom: {s['headerSpacing']}mm; }}
.body-area {{ min-height: 80mm; color: #aaa; font-style: italic; padding: 10mm 0;
  border-top: 1px solid #e4e4e7; border-bottom: 1px solid #e4e4e7; text-align: center; }}
.footer {{ padding-top: {s['footerSpacing']}mm; }}
table {{ border-collapse: collapse; width: 100%; margin: 6px 0; table-layout: fixed; }}
td, th {{ border: 1px solid #e4e4e7; padding: 0.1em 0.3em; vertical-align: top;
  word-break: break-word; overflow-wrap: anywhere; font-size: {fs}px; font-family: {ff}; }}
th {{ background-color: #f4f4f5; font-weight: 600; text-align: left; }}
p {{ margin: 0; padding: 0; }}
p + p {{ margin-top: 2px; }}
h1 {{ font-size: 1.55em; font-weight: 700; margin: 0.5em 0 0.25em; }}
h2 {{ font-size: 1.3em; font-weight: 700; margin: 0.4em 0 0.2em; }}
h3 {{ font-size: 1.1em; font-weight: 600; margin: 0.3em 0 0.15em; }}
img {{ max-width: 100%; height: auto; }}
mark {{ background-color: #fde047; padding: 0 2px; }}
</style></head>
<body>
<div class="header">{_clean(header_html)}</div>
<div class="body-area">[Report Body Content Area]</div>
<div class="footer">{_clean(footer_html)}</div>
</body></html>"""

    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buf, encoding='utf-8')
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════
# DOCX EXPORT
# ═══════════════════════════════════════════════════════════════════
def export_docx(header_html: str, footer_html: str, description: str, name: str) -> bytes:
    from docx import Document
    from docx.shared import Pt, Mm, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from bs4 import BeautifulSoup, NavigableString
    from PIL import Image as PILImage

    s = _parse_settings(description)
    dim = PAGE_DIMS.get(s['pageSize'], (210, 297))
    pw = dim[0] if s['orientation'] == 'portrait' else dim[1]
    ph = dim[1] if s['orientation'] == 'portrait' else dim[0]
    m = s['margins']
    content_width_mm = pw - m['left'] - m['right']

    doc = Document()
    # Set default font & paragraph spacing to match frontend (margin: 0)
    style = doc.styles['Normal']
    font = style.font
    ff = s.get('fontFamily', 'Arial').split(',')[0].strip().strip("'\"")
    font.name = ff
    try:
        font.size = Pt(float(s.get('fontSize', '12')))
    except:
        font.size = Pt(11)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.6

    section = doc.sections[0]
    section.page_width = Mm(pw)
    section.page_height = Mm(ph)
    section.top_margin = Mm(m['top'])
    section.bottom_margin = Mm(m['bottom'])
    section.left_margin = Mm(m['left'])
    section.right_margin = Mm(m['right'])

    def _align(style_str):
        if not style_str: return None
        if 'center' in style_str: return WD_ALIGN_PARAGRAPH.CENTER
        if 'right' in style_str: return WD_ALIGN_PARAGRAPH.RIGHT
        if 'justify' in style_str: return WD_ALIGN_PARAGRAPH.JUSTIFY
        return WD_ALIGN_PARAGRAPH.LEFT

    def _apply_run_format(run, tag, styles=None):
        styles = styles or {}
        if tag.name in ('strong', 'b') or styles.get('font-weight') in ('bold', '700'):
            run.bold = True
        if tag.name in ('em', 'i') or styles.get('font-style') == 'italic':
            run.italic = True
        if tag.name == 'u' or 'underline' in styles.get('text-decoration', ''):
            run.underline = True
        if tag.name in ('s', 'strike') or 'line-through' in styles.get('text-decoration', ''):
            run.font.strike = True
        rgb = _css_color(styles.get('color'))
        if rgb:
            run.font.color.rgb = RGBColor(*rgb)
        fs = styles.get('font-size', '')
        if fs:
            num = re.match(r'([\d.]+)', fs)
            if num: run.font.size = Pt(float(num.group(1)))
        ff = styles.get('font-family', '')
        if ff:
            run.font.name = ff.split(',')[0].strip().strip("'\"")
        if tag.name == 'mark':
            from docx.enum.text import WD_COLOR_INDEX
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    def _collect_runs(el):
        """Recursively collect (type, value, tag) tuples."""
        runs = []
        for child in (el.children if hasattr(el, 'children') else []):
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip() or text == ' ':
                    runs.append(('text', text, el))
            elif child.name == 'br':
                runs.append(('break', None, None))
            elif child.name == 'img':
                runs.append(('image', child.get('src', ''), child))
            elif child.name in ('strong', 'b', 'em', 'i', 'u', 's', 'strike', 'span', 'mark'):
                for item in _collect_runs(child):
                    if item[0] == 'text':
                        runs.append(('text', item[1], child))
                    else:
                        runs.append(item)
            else:
                runs.extend(_collect_runs(child))
        return runs

    def _add_image_run(paragraph, src, tag):
        img_bytes = _b64_to_bytes(src)
        if not img_bytes:
            return
        try:
            pil = PILImage.open(io.BytesIO(img_bytes))
            w_px = pil.size[0]
            tag_w = tag.get('width', '') if tag else ''
            if tag_w:
                try: w_in = float(re.sub(r'[^\d.]', '', str(tag_w))) / 96.0
                except: w_in = min(w_px / 96.0, content_width_mm / 25.4)
            else:
                w_in = min(w_px / 96.0, content_width_mm / 25.4)
            run = paragraph.add_run()
            run.add_picture(io.BytesIO(img_bytes), width=Inches(w_in))
        except Exception as e:
            logger.warning(f"Image insert failed: {e}")

    def _add_paragraph(container, el, heading=False):
        styles = _parse_inline_style(el.get('style', '') if hasattr(el, 'get') else '')
        alignment = _align(styles.get('text-align', ''))

        if heading and el.name in ('h1','h2','h3'):
            level = int(el.name[1])
            p = container.add_heading('', level=level)
        else:
            p = container.add_paragraph()

        if alignment:
            p.alignment = alignment

        for rtype, rval, rtag in _collect_runs(el):
            if rtype == 'text' and rval:
                run = p.add_run(rval)
                if rtag is not None:
                    tag_styles = _parse_inline_style(rtag.get('style', '') if hasattr(rtag, 'get') else '')
                    _apply_run_format(run, rtag, tag_styles)
                # Inherit paragraph-level styles
                if styles.get('font-size') and not run.font.size:
                    num = re.match(r'([\d.]+)', styles['font-size'])
                    if num: run.font.size = Pt(float(num.group(1)))
                if styles.get('font-family') and not run.font.name:
                    run.font.name = styles['font-family'].split(',')[0].strip().strip("'\"")
                if styles.get('color') and not run.font.color.rgb:
                    rgb = _css_color(styles['color'])
                    if rgb: run.font.color.rgb = RGBColor(*rgb)
            elif rtype == 'break':
                p.add_run().add_break()
            elif rtype == 'image':
                _add_image_run(p, rval, rtag)
        return p

    def _set_cell_bg(cell, hex_color: str):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shading = OxmlElement('w:shd')
        shading.set(qn('w:fill'), hex_color.lstrip('#'))
        shading.set(qn('w:val'), 'clear')
        tcPr.append(shading)

    def _set_cell_borders(cell, color_hex='E4E4E7', width_val='4'):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        borders = OxmlElement('w:tcBorders')
        for edge in ('top', 'left', 'bottom', 'right'):
            el = OxmlElement(f'w:{edge}')
            el.set(qn('w:val'), 'single')
            el.set(qn('w:sz'), width_val)
            el.set(qn('w:color'), color_hex.lstrip('#'))
            el.set(qn('w:space'), '0')
            borders.append(el)
        tcPr.append(borders)

    def _set_cell_margins(cell, top=0, bottom=0, left=43, right=43):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        margins = OxmlElement('w:tcMar')
        for edge, val in [('top', top), ('bottom', bottom), ('start', left), ('end', right)]:
            el = OxmlElement(f'w:{edge}')
            el.set(qn('w:w'), str(val))
            el.set(qn('w:type'), 'dxa')
            margins.append(el)
        tcPr.append(margins)

    def _padding_css_to_twips(padding_str):
        """Convert CSS padding like '0.1em 0.3em' to top/bottom/left/right in twips."""
        if not padding_str:
            return 14, 14, 43, 43  # default: tight (0.1em 0.3em at ~12px)
        parts = padding_str.strip().split()
        try:
            base_px = float(s.get('fontSize', '12'))
            if len(parts) == 1:
                v = float(parts[0].replace('em','').replace('px','')) * (base_px if 'em' in padding_str else 1)
                tw = int(v * 15)  # px to twips approx
                return tw, tw, tw, tw
            elif len(parts) >= 2:
                vert = float(parts[0].replace('em','').replace('px','')) * (base_px if 'em' in parts[0] else 1)
                horiz = float(parts[1].replace('em','').replace('px','')) * (base_px if 'em' in parts[1] else 1)
                tv, th = int(vert * 15), int(horiz * 15)
                return tv, tv, th, th
        except:
            pass
        return 14, 14, 43, 43

    def _process_table(container, table_el):
        rows_el = table_el.find_all('tr', recursive=True)
        if not rows_el: return
        max_cols = 0
        for tr in rows_el:
            cols = sum(int(c.get('colspan', 1)) for c in tr.find_all(['td','th'], recursive=False))
            max_cols = max(max_cols, cols)
        if max_cols == 0: return

        tbl = container.add_table(rows=0, cols=max_cols)
        tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
        tbl.style = 'Table Grid'
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls
        tbl_pr = tbl._element.xpath('w:tblPr')[0]
        tbl_w = parse_xml(f'<w:tblW {nsdecls("w")} w:w="5000" w:type="pct"/>')
        tbl_pr.append(tbl_w)

        merged_cells = set()  # track (row_idx, col_idx) occupied by rowspan
        for ri, tr in enumerate(rows_el):
            row = tbl.add_row()
            ci = 0
            for cell_el in tr.find_all(['td','th'], recursive=False):
                while (ri, ci) in merged_cells:
                    ci += 1
                if ci >= max_cols: break
                cell = row.cells[ci]
                cs = _parse_inline_style(cell_el.get('style', ''))
                is_header = cell_el.name == 'th'

                # Background color
                bg = _css_color(cs.get('background-color'))
                if bg:
                    _set_cell_bg(cell, f"{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}")
                elif is_header:
                    _set_cell_bg(cell, 'f4f4f5')

                # Border color/width per cell
                bc = _css_color(cs.get('border-color'))
                bw_str = cs.get('border-width', '1px')
                bw_num = re.match(r'([\d.]+)', bw_str)
                bw_val = str(int(float(bw_num.group(1)) * 8)) if bw_num else '8'
                _set_cell_borders(cell, f"{bc[0]:02x}{bc[1]:02x}{bc[2]:02x}" if bc else 'E4E4E7', bw_val)

                # Cell padding from inline style
                pad = cs.get('padding', '')
                t, b, l, r = _padding_css_to_twips(pad)
                _set_cell_margins(cell, t, b, l, r)

                cell.text = ''
                _process_elements(cell, cell_el)

                # Merge: colspan and rowspan
                colspan = int(cell_el.get('colspan', 1))
                rowspan = int(cell_el.get('rowspan', 1))
                if rowspan > 1 or colspan > 1:
                    for mri in range(ri, ri + rowspan):
                        for mci in range(ci, ci + colspan):
                            if mri != ri or mci != ci:
                                merged_cells.add((mri, mci))
                if colspan > 1:
                    for x in range(1, colspan):
                        if ci + x < max_cols:
                            cell.merge(row.cells[ci + x])
                ci += colspan

    def _process_elements(container, parent):
        for child in parent.children:
            if isinstance(child, NavigableString):
                t = str(child).strip()
                if t: container.add_paragraph(t)
                continue
            if child.name in ('p', 'div'):
                _add_paragraph(container, child)
            elif child.name in ('h1','h2','h3'):
                _add_paragraph(container, child, heading=True)
            elif child.name == 'table':
                _process_table(container, child)
            elif child.name in ('ul', 'ol'):
                for li in child.find_all('li', recursive=False):
                    container.add_paragraph(li.get_text(), style='List Bullet' if child.name == 'ul' else 'List Number')
            elif child.name == 'img':
                p = container.add_paragraph()
                _add_image_run(p, child.get('src',''), child)
            elif hasattr(child, 'children'):
                _process_elements(container, child)

    # Build document
    header_soup = BeautifulSoup(_clean(header_html or ''), 'html.parser')
    footer_soup = BeautifulSoup(_clean(footer_html or ''), 'html.parser')

    if header_html and header_html.strip():
        _process_elements(doc, header_soup)

    # Separator
    p = doc.add_paragraph()
    run = p.add_run('─' * 60)
    run.font.color.rgb = RGBColor(200, 200, 200)
    p = doc.add_paragraph()
    run = p.add_run('[Report Body Content Area]')
    run.font.color.rgb = RGBColor(180, 180, 180)
    run.italic = True
    p = doc.add_paragraph()
    run = p.add_run('─' * 60)
    run.font.color.rgb = RGBColor(200, 200, 200)

    if footer_html and footer_html.strip():
        _process_elements(doc, footer_soup)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════
# XLSX EXPORT
# ═══════════════════════════════════════════════════════════════════
def export_xlsx(header_html: str, footer_html: str, description: str, name: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.drawing.image import Image as XlImage
    from openpyxl.utils import get_column_letter
    from bs4 import BeautifulSoup
    from PIL import Image as PILImage

    s = _parse_settings(description)
    global_ff = s.get('fontFamily', 'Arial').split(',')[0].strip().strip("'\"")
    try:
        global_fs = float(s.get('fontSize', '12'))
    except:
        global_fs = 12.0

    wb = Workbook()
    wb.remove(wb.active)

    def _get_cell_text_align(cell_el):
        """Get text-align from cell's inner <p> tag or from the cell itself."""
        st = _parse_inline_style(cell_el.get('style', ''))
        ta = st.get('text-align', '')
        if ta:
            return ta
        # Check inner p tags
        p = cell_el.find('p')
        if p:
            pst = _parse_inline_style(p.get('style', ''))
            return pst.get('text-align', '')
        return ''

    def _process_section(html: str, section_name: str):
        if not html or not html.strip(): return
        soup = BeautifulSoup(_clean(html), 'html.parser')
        tables = soup.find_all('table')
        images = soup.find_all('img')

        if not tables and not images:
            text = soup.get_text(strip=True)
            if text:
                ws = wb.create_sheet(section_name)
                ws['A1'] = section_name
                ws['A1'].font = Font(bold=True, size=14, name=global_ff)
                ws['A2'] = text
                ws['A2'].font = Font(size=global_fs, name=global_ff)
                ws.column_dimensions['A'].width = max(40, min(len(text), 80))
            return

        for tidx, table in enumerate(tables):
            sheet_name = section_name if len(tables) == 1 else f"{section_name} T{tidx+1}"
            ws = wb.create_sheet(sheet_name[:31])
            merged_coords = set()

            rows_el = table.find_all('tr')
            for ri, tr in enumerate(rows_el, 1):
                ci = 1
                for cell_el in tr.find_all(['td','th'], recursive=False):
                    while (ri, ci) in merged_coords:
                        ci += 1

                    cell = ws.cell(ri, ci)
                    cell.value = cell_el.get_text(strip=True)

                    st = _parse_inline_style(cell_el.get('style', ''))
                    is_header = cell_el.name == 'th'

                    # Font - apply global defaults then override with inline
                    fkw = {'name': global_ff, 'size': global_fs}
                    if is_header:
                        fkw['bold'] = True
                    fs = st.get('font-size', '')
                    if fs:
                        num = re.match(r'([\d.]+)', fs)
                        if num: fkw['size'] = float(num.group(1))
                    fc = _css_color(st.get('color'))
                    if fc: fkw['color'] = f"{fc[0]:02X}{fc[1]:02X}{fc[2]:02X}"
                    ff = st.get('font-family', '')
                    if ff: fkw['name'] = ff.split(',')[0].strip().strip("'\"")
                    cell.font = Font(**fkw)

                    # Background
                    bg = _css_color(st.get('background-color'))
                    if bg:
                        cell.fill = PatternFill('solid', fgColor=f"{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}")
                    elif is_header:
                        cell.fill = PatternFill('solid', fgColor='F4F4F5')

                    # Borders
                    bc = _css_color(st.get('border-color'))
                    border_color = f"{bc[0]:02X}{bc[1]:02X}{bc[2]:02X}" if bc else 'E4E4E7'
                    side = Side(style='thin', color=border_color)
                    cell.border = Border(left=side, right=side, top=side, bottom=side)

                    # Text alignment - check cell and inner p tags
                    ta = _get_cell_text_align(cell_el)
                    cell.alignment = Alignment(
                        horizontal=ta if ta else 'left',
                        wrap_text=True, vertical='top'
                    )

                    # Merge
                    colspan = int(cell_el.get('colspan', 1))
                    rowspan = int(cell_el.get('rowspan', 1))
                    if colspan > 1 or rowspan > 1:
                        ws.merge_cells(start_row=ri, start_column=ci,
                                       end_row=ri+rowspan-1, end_column=ci+colspan-1)
                        for mri in range(ri, ri+rowspan):
                            for mci in range(ci, ci+colspan):
                                if mri != ri or mci != ci:
                                    merged_coords.add((mri, mci))

                    ci += colspan

            # Auto-size columns
            for col in range(1, ws.max_column + 1):
                max_len = 8
                for row in range(1, ws.max_row + 1):
                    v = ws.cell(row, col).value
                    if v:
                        max_len = max(max_len, min(len(str(v)) + 2, 40))
                ws.column_dimensions[get_column_letter(col)].width = max_len

        # Images sheet
        if images:
            img_ws = wb.create_sheet(f"{section_name} Images"[:31])
            row_off = 1
            for img_el in images:
                img_bytes = _b64_to_bytes(img_el.get('src', ''))
                if img_bytes:
                    try:
                        pil = PILImage.open(io.BytesIO(img_bytes))
                        buf = io.BytesIO()
                        pil.save(buf, format='PNG')
                        buf.seek(0)
                        xl_img = XlImage(buf)
                        xl_img.width = min(pil.size[0], 600)
                        xl_img.height = int(pil.size[1] * (xl_img.width / pil.size[0]))
                        img_ws.add_image(xl_img, f'A{row_off}')
                        row_off += max(int(xl_img.height / 15) + 2, 5)
                    except Exception as e:
                        logger.warning(f"XLSX image failed: {e}")

    _process_section(header_html, 'Header')
    _process_section(footer_html, 'Footer')

    if not wb.sheetnames:
        ws = wb.create_sheet('Template Info')
        ws['A1'] = f'Template: {name}'
        ws['A1'].font = Font(bold=True, size=14, name=global_ff)
        ws['A2'] = 'No table data found in header/footer.'
        ws['A2'].font = Font(size=global_fs, name=global_ff)
        ws.column_dimensions['A'].width = 50

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
