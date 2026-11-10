"""Build an editable Word version of the book: docs/book/TinyBookOfEMT.docx

    pip install pypandoc_binary python-docx      (once)
    python docs/book/make_docx.py

The text, numbers and figures come from make_book.py (so they are the same as in the PDF and
checked against EMTSim). The HTML is converted with pandoc, which turns every equation into an
editable Word equation, and the look of the book (black heading bars, boxes, cover, "n | Page"
footer) is set up as Word styles, so you can change it in one place: Home > Styles.
"""
import os
import re
import subprocess
import sys

import pypandoc
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Inches, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_book  # noqa: E402

OUT = os.path.join(HERE, "TinyBookOfEMT.docx")
REF = os.path.join(HERE, "reference.docx")
BODY = "Georgia"
HAND = "Segoe Script"


# ------------------------------------------------------------ figures as PNG (Word-friendly)
_save_svg = make_book.save


def _save_both(fig, name):
    fig.savefig(os.path.join(make_book.FIG, name[:-4] + ".png"), dpi=220, facecolor="white")
    _save_svg(fig, name)


make_book.save = _save_both


# ------------------------------------------------------------ HTML for pandoc
def html_for_pandoc(path):
    with open(path, encoding="utf-8") as fh:
        s = fh.read()
    s = re.sub(r"<style>.*?</style>", "", s, flags=re.S)
    cover = ("<div custom-style='Cover Title'><p>Tiny book of EMT simulation</p></div>"
             "<div custom-style='Cover Subtitle'><p>Closing a switch</p></div>"
             "<div custom-style='Cover Image'><p><img src='fig/cover.png' height='3.9in'></p></div>"
             "<div custom-style='Cover Author'><p>By Amila Pathirana</p></div>")
    s = re.sub(r'<section class="cover">.*?</section>', cover, s, flags=re.S)
    # images: PNG, width as an attribute
    s = re.sub(r'src="fig/([\w]+)\.svg" style="width:(\d+)%"', r'src="fig/\1.png" width="\2%"', s)
    s = s.replace('<img src="fig/ghost.svg" class="ghost" alt="">',
                  "<div custom-style='Ghost'><p><img src='fig/ghost.png' width='38%'></p></div>")
    # boxes
    s = re.sub(r"<div class='box (\w+)'><div class='tag'>(.*?)</div>",
               lambda m: "<div custom-style='Box %s'><p><span custom-style='Box Tag'>%s</span></p>"
               % (m.group(1).capitalize(), m.group(2)), s)
    s = re.sub(r'<p class="answer">(.*?)</p>', r"<div custom-style='Box Answer'><p>\1</p></div>", s, flags=re.S)
    s = re.sub(r'<div class="cheat">', "<div>", s)
    s = re.sub(r"<div><h4>(.*?)</h4>", r"<div custom-style='Box Cheat'><p><span custom-style='Box Tag'>\1</span></p>", s)
    s = re.sub(r'<p style="text-indent:0;text-align:center">', "<p>", s)
    # small paragraph styles
    s = re.sub(r'<p class="step">(.*?)</p>', r"<div custom-style='Step'><p>\1</p></div>", s, flags=re.S)
    s = re.sub(r"<p class='words'>(.*?)</p>", r"<div custom-style='In Words'><p>\1</p></div>", s, flags=re.S)
    # equation numbers go inside the equation
    s = re.sub(r"</math><span class='eqn'>\((\d+)\)</span>",
               r"<mspace width='3em'/><mo>(</mo><mn>\1</mn><mo>)</mo></math>", s)
    s = s.replace('<h2 class="newpage">', "<h2>")
    s = re.sub(r"<title>.*?</title>", "", s)
    # units and word subscripts upright in Word equations
    s = re.sub(r"<mspace width='0.2em'/><mi mathvariant='normal'>([^<]+)</mi>", r"<mtext>&#8201;\1</mtext>", s)
    s = re.sub(r"<mi mathvariant='normal'>([A-Za-z,]{2,})</mi>", r"<mtext>\1</mtext>", s)
    # lists inside boxes become plain numbered paragraphs, so they keep the box style
    out, pos = [], 0
    for m in re.finditer(r"<div custom-style='Box \w+'>", s):
        if m.start() < pos:
            continue
        depth, j = 0, m.start()
        for t in re.finditer(r"<div\b|</div>", s[m.start():]):
            depth += 1 if t.group() != "</div>" else -1
            if depth == 0:
                j = m.start() + t.end()
                break
        block = s[m.start():j]

        def numbered(lm):
            items = re.findall(r"<li>(.*?)</li>", lm.group(2), flags=re.S)
            mark = (lambda k: "%d." % (k + 1)) if lm.group(1) == "ol" else (lambda k: "–")
            return "".join("<p>%s&#8194;%s</p>" % (mark(k), it.strip()) for k, it in enumerate(items))
        block = re.sub(r"<(ol|ul)[^>]*>(.*?)</\1>", numbered, block, flags=re.S)
        out.append(s[pos:m.start()]); out.append(block); pos = j
    out.append(s[pos:])
    return "".join(out)


# ------------------------------------------------------------ the reference document (all styles)
def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn("w:" + k), str(v))
    return e


def _ppr(style):
    return style.element.get_or_add_pPr()


def shade(style, fill, run=False):
    pr = style.element.get_or_add_rPr() if run else _ppr(style)
    for old in pr.findall(qn("w:shd")):
        pr.remove(old)
    pr.append(_el("w:shd", val="clear", color="auto", fill=fill))


def border(style, color="000000", sz=10, sides=("top", "left", "bottom", "right"), space=4):
    p = _ppr(style)
    for old in p.findall(qn("w:pBdr")):
        p.remove(old)
    b = OxmlElement("w:pBdr")
    for side in sides:
        b.append(_el("w:" + side, val="single", sz=sz, space=space, color=color))
    p.append(b)


def para_style(doc, name, base="Body Text"):
    st = doc.styles
    try:
        s = st[name]
    except KeyError:
        s = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = st[base]
    return s


def font(s, name=BODY, size=None, bold=None, italic=None, color=None):
    s.font.name = name
    rpr = s.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.append(rf)
    for k in ("ascii", "hAnsi", "cs", "eastAsia"):
        rf.set(qn("w:" + k), name)
    for k in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
        rf.attrib.pop(qn("w:" + k), None)
    if size: s.font.size = Pt(size)
    if bold is not None: s.font.bold = bold
    if italic is not None: s.font.italic = italic
    if color: s.font.color.rgb = RGBColor.from_string(color)


def fmt(s, before=0, after=6, align=None, first=None, left=None, right=None, keep=None, line=None):
    pf = s.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    if align is not None: pf.alignment = align
    pf.first_line_indent = Inches(first) if first is not None else None
    if left is not None: pf.left_indent = Inches(left)
    if right is not None: pf.right_indent = Inches(right)
    if keep is not None: pf.keep_with_next = keep
    if line is not None: pf.line_spacing = line


def page_field(run):
    for kind, text in (("begin", None), (None, " PAGE "), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            run._r.append(_el("w:fldChar", fldCharType=kind))
        else:
            t = OxmlElement("w:instrText" if text.strip() == "PAGE" else "w:t")
            t.set(qn("xml:space"), "preserve"); t.text = text
            run._r.append(t)


def make_reference():
    pandoc = pypandoc.get_pandoc_path()
    with open(REF, "wb") as fh:
        fh.write(subprocess.run([pandoc, "--print-default-data-file", "reference.docx"],
                                check=True, capture_output=True).stdout)
    doc = Document(REF)
    st = doc.styles
    J, C, L, R = WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT

    font(st["Normal"], size=12)
    for name in ("Body Text", "First Paragraph"):
        s = st[name]; font(s, size=12); fmt(s, after=6, align=J, first=0.25, line=1.15)
    font(st["Compact"], size=12); fmt(st["Compact"], after=2, align=J, line=1.15)
    for name, size, left in (("Heading 1", 15, 0.0), ("Heading 2", 13.5, 0.9), ("Heading 3", 12, 0.9)):
        s = st[name]
        font(s, size=size, bold=True, color="FFFFFF"); fmt(s, before=16, after=8, left=left, keep=True, first=0)
        shade(s, "000000")
        for old in s.element.get_or_add_rPr().findall(qn("w:i")):
            s.element.get_or_add_rPr().remove(old)
    for name in ("Image Caption", "Table Caption"):
        s = st[name]; font(s, size=10.5, italic=False); fmt(s, before=2, after=10, align=L, first=0)
    for name in ("Figure", "Captioned Figure"):
        try:
            s = st[name]; fmt(s, before=6, after=2, align=C, first=0, keep=True)
        except KeyError:
            pass
    s = para_style(doc, "Source Code", base="Normal"); fmt(s, before=4, after=8, first=0, left=0.1, line=1.0)
    font(s, "Consolas", 9); shade(s, "F2F2F2")
    border(s, "000000", sz=18, sides=("left",), space=6)
    font(st["Verbatim Char"], name="Consolas", size=9)

    # cover
    s = para_style(doc, "Cover Title"); font(s, HAND, 38, color="FFFFFF"); fmt(s, before=0, after=0, align=C, first=0, left=0.4, right=0.4, line=1.0)
    shade(s, "000000")
    s = para_style(doc, "Cover Subtitle"); font(s, HAND, 28, color="7F7F7F"); fmt(s, before=24, after=18, align=C, first=0)
    s = para_style(doc, "Cover Image"); fmt(s, before=0, after=0, align=C, first=0)
    s = para_style(doc, "Cover Author"); font(s, HAND, 20, color="FFFFFF"); fmt(s, before=40, after=0, align=C, first=0)
    shade(s, "000000")
    # small styles
    s = para_style(doc, "Step"); font(s, size=12, bold=True); fmt(s, before=8, after=4, first=0, left=0.9, keep=True)
    s = para_style(doc, "In Words"); font(s, size=11, italic=True, color="444444"); fmt(s, before=0, after=10, align=C, first=0)
    s = para_style(doc, "Ghost"); fmt(s, before=0, after=4, align=R, first=0)
    # box text (the frame and the background are a one-cell table, see boxes())
    for name in ("Box Remember", "Box Recipe", "Box Try", "Box Cheat"):
        s = para_style(doc, name); font(s, size=11.5); fmt(s, before=0, after=3, align=J, first=0, left=0, right=0, line=1.1)
    s = para_style(doc, "Box Answer", base="Box Try"); font(s, size=10, color="555555")
    try:
        t = st["Box Tag"]
    except KeyError:
        t = st.add_style("Box Tag", WD_STYLE_TYPE.CHARACTER)
    font(t, "Segoe Print", 10.5, color="FFFFFF"); shade(t, "000000", run=True)

    # page: US Letter, footer "n | Page", no footer on the cover
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(1.05)
    sec.top_margin, sec.bottom_margin = Inches(0.95), Inches(0.9)
    sec.different_first_page_header_footer = True
    f = sec.footer
    p = f.paragraphs[0] if f.paragraphs else f.add_paragraph()
    p.text = ""
    p.paragraph_format.alignment = L
    pPr = p._p.get_or_add_pPr()
    b = OxmlElement("w:pBdr"); b.append(_el("w:top", val="single", sz=4, space=4, color="D0D0D0")); pPr.append(b)
    r = p.add_run(); r.bold = True; r.font.size = Pt(10); r.font.name = "Calibri"; page_field(r)
    r = p.add_run(" | "); r.bold = True; r.font.size = Pt(10); r.font.name = "Calibri"
    r = p.add_run("P a g e"); r.font.size = Pt(10); r.font.name = "Calibri"; r.font.color.rgb = RGBColor(0x7F, 0x7F, 0x7F)
    doc.save(REF)


# ------------------------------------------------------------ after pandoc
def finish(path):
    doc = Document(path)
    for p in doc.paragraphs:
        if p.style.name.startswith("Heading 1") and p.text.strip() in ("1. Introduction", "Cheat sheet"):
            p.paragraph_format.page_break_before = True
        if p.style.name == "Cover Title":
            p.paragraph_format.space_before = Pt(0)
    # tables: centred, a rule under the header row and under every row
    for t in doc.tables:
        tblPr = t._tbl.tblPr
        for old in tblPr.findall(qn("w:jc")):
            tblPr.remove(old)
        tblPr.append(_el("w:jc", val="center"))
        b = OxmlElement("w:tblBorders")
        b.append(_el("w:top", val="single", sz=8, space=0, color="000000"))
        b.append(_el("w:bottom", val="single", sz=8, space=0, color="000000"))
        b.append(_el("w:insideH", val="single", sz=4, space=0, color="BBBBBB"))
        for old in tblPr.findall(qn("w:tblBorders")):
            tblPr.remove(old)
        tblPr.append(b)
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.first_line_indent = Inches(0)
                    p.paragraph_format.space_after = Pt(1)
                    for r in p.runs:
                        r.font.size = Pt(10.5)
        for cell in t.rows[0].cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True
    doc.save(path)


BOXES = {"Remember": ("C55A11", None), "Recipe": ("000000", "FFF8D6"), "Try": ("000000", "F4F4F4"),
         "Cheat": ("000000", None)}


def boxes(path):
    """Put each box (a run of 'Box ...' paragraphs, with any equations in it) into a one-cell table:
    Word draws a clean frame around text, lists and equations alike, and it is easy to edit."""
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    body = doc.element.body
    groups, cur = [], None
    for el in list(body):
        if el.tag != qn("w:p"):
            cur = None
            continue
        p = Paragraph(el, doc)
        name = p.style.name if p.style is not None else ""
        starts = bool(p.runs) and p.runs[0].style is not None and p.runs[0].style.name == "Box Tag"
        if name.startswith("Box ") and name != "Box Answer" and (starts or cur is None or cur[0] != name.split()[1]):
            cur = [name.split()[1], [el]]
            groups.append(cur)
        elif cur is not None and (name.startswith("Box ") or el.xpath(".//m:oMathPara")):
            cur[1].append(el)
        else:
            cur = None
    width = 9216     # text width in twips (8.5 in - 2 x 1.05 in)
    for kind, els in groups:
        color, fill = BOXES[kind]
        tbl = OxmlElement("w:tbl")
        tblPr = OxmlElement("w:tblPr")
        tblPr.append(_el("w:tblW", w=width, type="dxa"))
        tblPr.append(_el("w:jc", val="center"))
        b = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right"):
            b.append(_el("w:" + side, val="single", sz=12, space=0, color=color))
        tblPr.append(b)
        mar = OxmlElement("w:tblCellMar")
        for side, w in (("top", 40), ("left", 150), ("bottom", 60), ("right", 150)):
            mar.append(_el("w:" + side, w=w, type="dxa"))
        tblPr.append(mar)
        tbl.append(tblPr)
        grid = OxmlElement("w:tblGrid"); grid.append(_el("w:gridCol", w=width)); tbl.append(grid)
        tr = OxmlElement("w:tr"); tc = OxmlElement("w:tc"); tcPr = OxmlElement("w:tcPr")
        tcPr.append(_el("w:tcW", w=width, type="dxa"))
        cb = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right"):
            cb.append(_el("w:" + side, val="single", sz=12, space=0, color=color))
        tcPr.append(cb)
        if fill:
            tcPr.append(_el("w:shd", val="clear", color="auto", fill=fill))
        tc.append(tcPr); tr.append(tc); tbl.append(tr)
        trPr = OxmlElement("w:trPr"); trPr.append(_el("w:cantSplit")); tr.insert(0, trPr)
        els[0].addprevious(tbl)
        for el in els:
            tc.append(el)
        gap = OxmlElement("w:p")
        pPr = OxmlElement("w:pPr"); pPr.append(_el("w:spacing", before=0, after=0, line=200, lineRule="exact"))
        gap.append(pPr)
        tbl.addnext(gap)
    doc.save(path)


def build():
    html = make_book.build()
    make_reference()
    src = html_for_pandoc(html)
    pypandoc.convert_text(src, "docx", format="html", outputfile=OUT,
                          extra_args=["--reference-doc=" + REF, "--resource-path=" + HERE, "--shift-heading-level-by=-1"])
    finish(OUT)
    boxes(OUT)
    os.remove(REF)
    print("  wrote", os.path.relpath(OUT, make_book.ROOT))
    return OUT


if __name__ == "__main__":
    build()
