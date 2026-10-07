import sys
from fontTools.ttLib import TTFont, newTable
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

def convert(src, dst):
    font = TTFont(src)
    gs = font.getGlyphSet()
    glyf = newTable("glyf"); glyf.glyphOrder = font.getGlyphOrder(); glyf.glyphs = {}
    for name in font.getGlyphOrder():
        pen = TTGlyphPen(gs)
        gs[name].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
        glyf[name] = pen.glyph()
    font["glyf"] = glyf
    font["loca"] = newTable("loca")
    del font["CFF "]
    if "VORG" in font: del font["VORG"]
    font["maxp"] = newTable("maxp"); m = font["maxp"]
    m.tableVersion = 0x00010000
    for k in ("maxZones","maxTwilightPoints","maxStorage","maxFunctionDefs","maxInstructionDefs","maxStackElements","maxSizeOfInstructions","maxComponentElements"):
        setattr(m, k, 0)
    m.maxZones = 1
    font["head"].glyphDataFormat = 0
    font["post"].formatType = 2.0; font["post"].extraNames = []; font["post"].mapping = {}
    font["post"].glyphOrder = font.getGlyphOrder()
    font.sfntVersion = "\x00\x01\x00\x00"
    font.save(dst)

for w in ("Regular", "Bold", "SemiBold", "Italic", "Medium"):
    convert(f"/usr/share/fonts/opentype/inter/Inter-{w}.otf", f"Inter-{w}.ttf")
print("ok")
